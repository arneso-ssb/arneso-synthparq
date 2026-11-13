"""Synthetic Parquet test data generated from a reviewed profile.

A profile is a human-readable JSON file produced in the production environment by
:func:`profile_parquet`. Only columns explicitly allowed in an export config get
statistics. Dataset-level metadata is exported independently of column roles and
must also be reviewed. :func:`generate_parquet` needs only the approved profile.
"""

import itertools
import json
import math
import string
import warnings
from collections import Counter
from collections.abc import Sequence
from datetime import date
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from decimal import localcontext
from importlib.metadata import version
from pathlib import Path
from typing import Any
from typing import cast

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from synthparq._arrow import Array as _Array
from synthparq._arrow import ChunkedArray as _ChunkedArray
from synthparq._constraints import reconcile
from synthparq._constraints import verify
from synthparq._files import atomic_output
from synthparq._files import check_output
from synthparq._periods import _NATIVE_PERIOD
from synthparq._periods import _PERIOD_FORMATS
from synthparq._periods import _format_period
from synthparq._periods import _native_period
from synthparq._periods import _parse_period
from synthparq._periods import _period_range
from synthparq._types import _from_json
from synthparq._types import _is_measure
from synthparq._types import _is_numeric
from synthparq._types import _is_string
from synthparq._types import _to_json
from synthparq._types import _value_type
from synthparq._types import string_to_type
from synthparq._types import type_to_string
from synthparq._validation import config_shape
from synthparq._validation import integer
from synthparq._validation import profile_shape
from synthparq._validation import read_json

FORMAT_VERSION = 1
ROLES = ("schema_only", "pattern", "code", "numeric_stats")
HISTOGRAM_BINS = 10
ID_LIKE_RATIO = 0.5
RANDOM_WALK_STEP = 0.05
_DEFAULT_CONFIG: dict[str, Any] = {
    "k": 5,
    "significant_digits": 3,
    "max_key_size": 5,
    "mapping_max_distinct": 10_000,
    "timeseries": "auto",
    "force_code": [],
}
_PERIOD_NAME_HINTS = (
    "period",
    "dato",
    "date",
    "tid",
    "time",
    "aar",
    "year",
    "maaned",
    "month",
    "kvartal",
    "quarter",
)


def init_config(
    parquet_file: Path, config_file: Path, *, overwrite: bool = False
) -> Path:
    """Write an export config template listing every column as ``schema_only``.

    Only the Parquet schema is read, never the data.

    Args:
        parquet_file: The Parquet file to be profiled.
        config_file: Where to write the JSON config template.
        overwrite: Whether to replace an existing output file.

    Returns:
        The path of the written config file.
    """
    check_output(config_file, (parquet_file,), overwrite)
    schema = pq.read_schema(parquet_file)
    _check_schema(schema)
    config = {
        **_DEFAULT_CONFIG,
        "columns": dict.fromkeys(schema.names, "schema_only"),
    }
    _write_json(config_file, config, overwrite)
    return config_file


def profile_parquet(
    parquet_file: Path,
    profile_file: Path,
    config_file: Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Write a reviewable profile of a Parquet file.

    Without a config columns have no statistics. Dataset-level metadata
    (row count, keys, mappings and detected periods) is still exported.
    Review every profile before transferring it outside production.

    Args:
        parquet_file: The Parquet file to profile.
        profile_file: Where to write the JSON profile.
        config_file: Export config assigning a role to each column.
        overwrite: Whether to replace an existing output file.

    Returns:
        The path of the written profile.
    """
    inputs = (parquet_file,) if config_file is None else (parquet_file, config_file)
    check_output(profile_file, inputs, overwrite)
    schema = pq.read_schema(parquet_file)
    _check_schema(schema)
    config = _load_config(config_file, schema)
    table = pq.read_table(parquet_file)
    digits: int = config["significant_digits"]
    roles: dict[str, str] = config["columns"]

    columns = []
    for field in table.schema:
        role = roles[field.name]
        entry: dict[str, Any] = {
            "name": field.name,
            "type": type_to_string(field.type),
            "nullable": field.nullable,
            "role": role,
        }
        if role != "schema_only":
            entry["stats"] = _column_stats(
                field.name,
                table.column(field.name),
                role,
                config,
            )
        columns.append(entry)

    codes = _factorize(table)
    period_formats = _period_formats(table)
    primary_key = _find_primary_key(
        table, codes, config["max_key_size"], period_formats
    )
    profile = {
        "format_version": FORMAT_VERSION,
        "producer": {
            "name": "arneso-synthparq",
            "version": version("arneso-synthparq"),
        },
        "row_count": _round_count(table.num_rows, digits),
        "export_settings": {"k": config["k"], "significant_digits": digits},
        "columns": columns,
        "primary_key": primary_key,
        "mappings": _find_mappings(table, codes, config["mapping_max_distinct"]),
        "timeseries": _detect_timeseries(
            table, config, primary_key, period_formats, codes
        ),
    }
    _write_json(profile_file, profile, overwrite)
    return profile_file


def generate_parquet(
    profile_file: Path,
    output_file: Path,
    seed: int = 0,
    n_rows: int | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Generate a synthetic Parquet file from a profile.

    Args:
        profile_file: A profile written by :func:`profile_parquet`.
        output_file: Where to write the synthetic Parquet file.
        seed: Random seed; the same seed gives identical output.
        n_rows: Approximate number of rows. Defaults to the profiled row count.
            Time series always cover the full period range, so the actual
            count is rounded up to a whole number of series.
        overwrite: Whether to replace an existing output file.

    Returns:
        The path of the written Parquet file.

    Raises:
        ValueError: If the profile format version is not supported.
    """
    check_output(output_file, (profile_file,), overwrite)
    integer(seed, "seed", 0)
    if n_rows is not None:
        integer(n_rows, "n_rows", 0)
    profile = read_json(profile_file)
    profile_shape(profile, string_to_type)
    for column in profile["columns"]:
        value_type = _value_type(string_to_type(column["type"]))
        if (
            pa.types.is_decimal(value_type)
            and not 0 <= value_type.scale <= value_type.precision
        ):
            raise ValueError("Parquet Decimal scale must be between zero and precision")
        if column["role"] == "code":
            try:
                values = [
                    _from_json(item["value"], value_type)
                    for item in column["stats"]["values"]
                ]
                _to_arrow(values, string_to_type(column["type"]))
                if len(set(values)) != len(values):
                    raise ValueError("Duplicate codes")
            except (ValueError, TypeError, ArithmeticError, pa.ArrowException):
                raise ValueError(
                    "Invalid or duplicate code values for the declared column type"
                ) from None
    generator = _Generator(profile, np.random.default_rng(seed))
    names = [column["name"] for column in profile["columns"]]
    target = profile["row_count"] if n_rows is None else n_rows
    timeseries: dict[str, Any] | None = profile.get("timeseries")
    primary_key: list[str] = profile.get("primary_key") or []

    data: dict[str, list[Any]] = {}
    n_series, n_periods = 1, 1
    if target == 0:
        fields = [
            pa.field(c["name"], string_to_type(c["type"]), c["nullable"])
            for c in profile["columns"]
        ]
        table = pa.Table.from_arrays(
            [_to_arrow([], f.type) for f in fields], schema=pa.schema(fields)
        )
        with atomic_output(output_file, overwrite) as temporary:
            pq.write_table(table, temporary)
        return output_file
    if timeseries is not None:
        period = timeseries["period"]
        periods = _period_range(timeseries, generator.value_type(period))
        n_periods = len(periods)
        if not n_periods:
            raise ValueError("Invalid or reversed period range in profile")
        series_keys: list[str] = timeseries["series_keys"]
        if series_keys:
            series = generator.unique_rows(
                series_keys, max(1, math.ceil(target / n_periods))
            )
            n_series = len(series[series_keys[0]])
            for name, values in series.items():
                data[name] = [value for value in values for _ in range(n_periods)]
        elif target > n_periods:
            raise ValueError(
                "A time series without series keys has capacity for only one series"
            )
        data[period] = periods * n_series
        roots = [period, *series_keys]
        n = n_series * n_periods
    elif primary_key:
        data.update(generator.unique_rows(primary_key, target))
        roots = primary_key
        n = len(data[primary_key[0]])
    else:
        roots = []
        n = target

    order, parents = _plan(names, roots, profile.get("mappings", []))
    for name in order:
        if name in data:
            continue
        if timeseries is not None and name in timeseries["values"]:
            data[name] = generator.random_walk(name, n_series, n_periods)
        elif name in parents:
            parent, kind = parents[name]
            data[name] = generator.derive(name, data[parent], kind)
        else:
            data[name] = generator.sample(name, n)

    fields = [
        pa.field(column["name"], string_to_type(column["type"]), column["nullable"])
        for column in profile["columns"]
    ]
    reconcile(data, profile.get("mappings", []))
    table = pa.Table.from_arrays(
        [_to_arrow(data[field.name], field.type) for field in fields],
        schema=pa.schema(fields),
    )
    verify(table, profile, n)
    with atomic_output(output_file, overwrite) as temporary:
        pq.write_table(table, temporary)
    return output_file


def _write_json(path: Path, content: dict[str, Any], overwrite: bool = False) -> None:
    text = json.dumps(content, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    with atomic_output(path, overwrite) as temporary:
        temporary.write_text(text, encoding="utf-8")


def _load_config(config_file: Path | None, schema: pa.Schema) -> dict[str, Any]:
    config: dict[str, Any] = {**_DEFAULT_CONFIG, "columns": {}}
    if config_file is not None:
        user = read_json(config_file)
        unknown_settings = set(user) - set(config)
        if unknown_settings:
            raise ValueError(f"Unknown config settings: {sorted(unknown_settings)}")
        config.update(user)
        config_shape(config, schema.names)
        columns = dict(config["columns"])
        unknown = [name for name in columns if name not in schema.names]
        if unknown:
            raise ValueError(f"Config lists columns not in the file: {unknown}")
        missing = [name for name in schema.names if name not in columns]
        if missing:
            warnings.warn(
                f"Columns missing from config are exported as schema_only: {missing}",
                UserWarning,
                stacklevel=3,
            )
    else:
        columns = {}

    for field in schema:
        role = columns.setdefault(field.name, "schema_only")
        if not isinstance(role, str) or role not in ROLES:
            raise ValueError(f"Unknown role {role!r} for column {field.name!r}")
        value_type = _value_type(field.type)
        if role == "numeric_stats" and not _is_numeric(value_type):
            raise ValueError(f"Column {field.name!r} is not numeric")
        if role == "pattern" and not _is_string(value_type):
            raise ValueError(f"Column {field.name!r} is not a string column")
    unknown_forced = set(config["force_code"]) - set(schema.names)
    if unknown_forced:
        raise ValueError(f"force_code lists unknown columns: {sorted(unknown_forced)}")
    timeseries = config["timeseries"]
    if not (timeseries in ("auto", "none") or isinstance(timeseries, dict)):
        raise ValueError("timeseries must be 'auto', 'none' or an object")
    config["columns"] = columns
    return config


def _check_schema(schema: pa.Schema) -> None:
    if not schema.names or len(set(schema.names)) != len(schema.names):
        raise ValueError("Schema must have at least one column and unique column names")
    for field in schema:
        type_to_string(field.type)
        value_type = _value_type(field.type)
        if (
            pa.types.is_decimal(value_type)
            and not 0 <= value_type.scale <= value_type.precision
        ):
            raise ValueError("Parquet Decimal scale must be between zero and precision")


def _decoded(column: _ChunkedArray) -> _ChunkedArray:
    if pa.types.is_dictionary(column.type):
        return column.cast(column.type.value_type)
    return column


def _round_sig(value: float, digits: int) -> float:
    if value == 0 or not math.isfinite(value):
        return float(value)
    return round(float(value), digits - 1 - math.floor(math.log10(abs(value))))


def _round_count(count: int, digits: int) -> int:
    return int(_round_sig(count, digits))


def _column_stats(
    name: str, column: _ChunkedArray, role: str, config: dict[str, Any]
) -> dict[str, Any]:
    k: int = config["k"]
    digits: int = config["significant_digits"]
    values = _decoded(column).to_pylist()
    non_null = [value for value in values if value is not None]
    null_fraction = 1 - len(non_null) / len(values) if values else 0.0
    stats: dict[str, Any] = {"null_fraction": _round_sig(null_fraction, digits)}
    if role == "code":
        stats.update(_code_stats(name, non_null, k, digits, config["force_code"]))
    elif role == "numeric_stats":
        stats.update(_numeric_stats(non_null, k, digits))
    elif role == "pattern":
        stats.update(_pattern_stats(non_null, digits))
    return stats


def _code_stats(
    name: str, non_null: list[Any], k: int, digits: int, forced: Sequence[str]
) -> dict[str, Any]:
    counts = Counter(non_null)
    if non_null and len(counts) > ID_LIKE_RATIO * len(non_null) and name not in forced:
        raise ValueError(
            f"Column {name!r} looks like an identifier. Use role 'pattern', or list it in "
            "'force_code' if its values are not sensitive."
        )
    kept = sorted(
        ((value, count) for value, count in counts.items() if count >= k),
        key=lambda item: (-item[1], str(item[0])),
    )
    suppressed = len(non_null) - sum(count for _, count in kept)
    return {
        "values": [
            {"value": _to_json(value), "count": _round_count(count, digits)}
            for value, count in kept
        ],
        "suppressed_fraction": _round_sig(
            suppressed / len(non_null) if non_null else 0.0, digits
        ),
    }


def _numeric_stats(non_null: list[Any], k: int, digits: int) -> dict[str, Any]:
    array = np.array([float(value) for value in non_null], dtype=np.float64)
    array = array[np.isfinite(array)]
    if len(array) < k:
        return {"suppressed": True}
    low, high = float(array.min()), float(array.max())
    if low == high:
        edges, counts = [low, high], [len(array)]
    else:
        raw_counts, raw_edges = np.histogram(array, bins=HISTOGRAM_BINS)
        edges, counts = _merge_small_bins(
            [float(edge) for edge in raw_edges], [int(c) for c in raw_counts], k
        )
    rounded_edges = np.maximum.accumulate([_round_sig(edge, digits) for edge in edges])
    return {
        "min": _round_sig(low, digits),
        "max": _round_sig(high, digits),
        "mean": _round_sig(float(array.mean()), digits),
        "std": _round_sig(float(array.std()), digits),
        "distinct_count": _round_count(len(np.unique(array)), digits),
        "histogram": {
            "edges": [float(edge) for edge in rounded_edges],
            "fractions": [_round_sig(count / len(array), digits) for count in counts],
        },
    }


def _merge_small_bins(
    edges: list[float], counts: list[int], k: int
) -> tuple[list[float], list[int]]:
    merged_edges, merged_counts, pending = [edges[0]], [], 0
    for count, upper in zip(counts, edges[1:], strict=True):
        pending += count
        if pending >= k:
            merged_counts.append(pending)
            merged_edges.append(upper)
            pending = 0
    if pending:
        if merged_counts:
            merged_counts[-1] += pending
            merged_edges[-1] = edges[-1]
        else:
            merged_counts.append(pending)
            merged_edges.append(edges[-1])
    return merged_edges, merged_counts


def _pattern_stats(non_null: list[Any], digits: int) -> dict[str, Any]:
    strings = [str(value) for value in non_null]
    if not strings:
        return {"distinct_count": 0}
    classes = {_character_class(char) for text in set(strings) for char in text}
    lengths = [len(text) for text in strings]
    return {
        "min_length": min(lengths),
        "max_length": max(lengths),
        "character_classes": sorted(classes),
        "distinct_count": _round_count(len(set(strings)), digits),
    }


def _character_class(char: str) -> str:
    if char.isdigit():
        return "digit"
    if char.isupper():
        return "upper"
    if char.islower():
        return "lower"
    if char.isspace():
        return "space"
    return "other"


def _factorize(table: pa.Table) -> dict[str, tuple[npt.NDArray[np.int64], int]]:
    codes = {}
    for name in table.column_names:
        series = _decoded(table.column(name)).to_pandas()
        values, uniques = pd.factorize(series, use_na_sentinel=False)
        codes[name] = (values.astype(np.int64), len(uniques))
    return codes


def _n_unique(
    columns: Sequence[str], codes: dict[str, tuple[npt.NDArray[np.int64], int]]
) -> int:
    ids = codes[columns[0]][0]
    for name in columns[1:]:
        column_codes, cardinality = codes[name]
        combined = ids * cardinality + column_codes
        ids = pd.factorize(combined)[0].astype(np.int64)
    return int(ids.max()) + 1 if len(ids) else 0


def _find_primary_key(
    table: pa.Table,
    codes: dict[str, tuple[npt.NDArray[np.int64], int]],
    max_size: int,
    period_formats: dict[str, str],
) -> list[str] | None:
    n = table.num_rows
    if n < 2:
        return None
    candidates = [
        field.name
        for field in table.schema
        if not _is_measure(field.type)
        and codes[field.name][1] > 1
        and table.column(field.name).null_count == 0
    ]
    for size in range(1, max_size + 1):
        found = [
            list(combo)
            for combo in itertools.combinations(candidates, size)
            if math.prod(codes[name][1] for name in combo) >= n
            and _n_unique(combo, codes) == n
        ]
        if found:
            with_period = [key for key in found if set(key) & set(period_formats)]
            return (with_period or found)[0]
    return None


def _find_mappings(
    table: pa.Table,
    codes: dict[str, tuple[npt.NDArray[np.int64], int]],
    max_distinct: int,
) -> list[dict[str, str]]:
    eligible = [
        field.name
        for field in table.schema
        if not _is_measure(field.type)
        and 1 < codes[field.name][1] <= max_distinct
        and codes[field.name][1] < table.num_rows
    ]
    mappings = []
    for first, second in itertools.combinations(eligible, 2):
        pairs = _n_unique([first, second], codes)
        first_determines = pairs == codes[first][1]
        second_determines = pairs == codes[second][1]
        if first_determines and second_determines:
            mappings.append({"from": first, "to": second, "kind": "1:1"})
        elif first_determines:
            mappings.append({"from": first, "to": second, "kind": "N:1"})
        elif second_determines:
            mappings.append({"from": second, "to": first, "kind": "N:1"})
    return mappings


def _period_formats(table: pa.Table) -> dict[str, str]:
    formats = {}
    for field in table.schema:
        value_type = _value_type(field.type)
        if pa.types.is_date(value_type) or pa.types.is_timestamp(value_type):
            values = _decoded(table.column(field.name)).to_pylist()
            if not values or any(value is None for value in values):
                continue
            if pa.types.is_timestamp(value_type) and any(
                pd.Timestamp(value).time() != datetime.min.time()
                for value in values
                if value is not None
            ):
                continue
            formats[field.name] = _NATIVE_PERIOD
            continue
        if not (_is_string(value_type) or pa.types.is_integer(value_type)):
            continue
        texts = {str(v) for v in _decoded(table.column(field.name)).to_pylist()}
        texts.discard("None")
        if not texts:
            continue
        for period_format in _PERIOD_FORMATS:
            if all(_parse_period(text, period_format) for text in texts):
                formats[field.name] = period_format
                break
    return formats


def _detect_timeseries(
    table: pa.Table,
    config: dict[str, Any],
    primary_key: list[str] | None,
    period_formats: dict[str, str],
    codes: dict[str, tuple[npt.NDArray[np.int64], int]],
) -> dict[str, Any] | None:
    setting = config["timeseries"]
    if setting == "none":
        return None
    if isinstance(setting, dict):
        period = setting["period"]
        series_keys = list(setting["series_keys"])
        values = list(setting["values"])
        for name in [period, *series_keys, *values]:
            if name not in table.column_names:
                raise ValueError(f"Unknown timeseries column: {name!r}")
        if period not in period_formats:
            raise ValueError(f"Column {period!r} is not a recognised period column")
        if any(
            not _is_numeric(_value_type(table.schema.field(name).type))
            for name in values
        ):
            raise ValueError("Time-series value columns must be numeric")
        structural = [period, *series_keys]
        if (
            any(table.column(name).null_count for name in structural)
            or _n_unique(structural, codes) != table.num_rows
        ):
            raise ValueError(
                "Time-series period and series keys must uniquely identify rows without nulls"
            )
    else:
        if primary_key is None:
            return None
        candidates = [name for name in primary_key if name in period_formats]
        if not candidates:
            return None
        period = sorted(
            candidates,
            key=lambda name: not any(h in name.lower() for h in _PERIOD_NAME_HINTS),
        )[0]
        series_keys = [name for name in primary_key if name != period]
        values = [
            field.name
            for field in table.schema
            if field.name not in primary_key
            and (
                _is_measure(field.type)
                or (
                    pa.types.is_integer(_value_type(field.type))
                    and config["columns"][field.name] == "numeric_stats"
                )
            )
        ]
        if not values:
            return None

    period_format = period_formats[period]
    raw = [v for v in _decoded(table.column(period)).to_pylist() if v is not None]
    if period_format == _NATIVE_PERIOD:
        timestamps = [pd.Timestamp(value) for value in raw]
        monthly = all(
            t.day == 1 and t.time() == datetime.min.time() for t in timestamps
        )
        frequency = "M" if monthly else "D"
        periods = [_native_period(value, frequency) for value in raw]
        start = min(periods).start_time.date().isoformat()
        end = max(periods).start_time.date().isoformat()
    else:
        frequency = _PERIOD_FORMATS[period_format][1]
        parsed = [_parse_period(str(value), period_format) for value in set(raw)]
        periods = [p for p in parsed if p is not None]
        start = _format_period(min(periods), period_format)
        end = _format_period(max(periods), period_format)

    n_series = _n_unique(series_keys, codes) if series_keys else 1
    return {
        "period": period,
        "period_format": period_format,
        "frequency": frequency,
        "start": start,
        "end": end,
        "series_keys": series_keys,
        "values": values,
        "n_series": _round_count(n_series, config["significant_digits"]),
    }


def _plan(
    names: list[str], roots: list[str], mappings: list[dict[str, str]]
) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """Order columns so determinants come first, and pick a parent for each.

    Args:
        names: All column names in schema order.
        roots: Columns already generated as keys or periods.
        mappings: Recorded pairwise functional dependencies.

    Returns:
        The generation order and, per derived column, its (parent, kind).
    """
    determinants: dict[str, list[tuple[str, str]]] = {name: [] for name in names}
    determined_count: Counter[str] = Counter()
    for mapping in mappings:
        source, target, kind = mapping["from"], mapping["to"], mapping["kind"]
        determinants[target].append((source, kind))
        determined_count[source] += 1
        if kind == "1:1":
            determinants[source].append((target, kind))
            determined_count[target] += 1
    rest = sorted(
        (name for name in names if name not in roots),
        key=lambda name: -determined_count[name],
    )
    order = [*roots, *rest]
    position = {name: index for index, name in enumerate(order)}
    parents = {}
    for name in rest:
        options = [
            option
            for option in determinants[name]
            if position[option[0]] < position[name]
        ]
        if options:
            parents[name] = min(
                options,
                key=lambda option: (determined_count[option[0]], position[option[0]]),
            )
    return order, parents


def _to_arrow(values: list[Any], data_type: pa.DataType) -> _Array:
    if pa.types.is_dictionary(data_type):
        array = pa.array(values, type=data_type.value_type).dictionary_encode()
        return cast("pa.Array[Any]", array.cast(data_type))
    return pa.array(values, type=data_type)


class _Generator:
    def __init__(self, profile: dict[str, Any], rng: np.random.Generator) -> None:
        self.rng = rng
        self.columns: dict[str, dict[str, Any]] = {
            column["name"]: column for column in profile["columns"]
        }
        self._domains: dict[str, list[Any]] = {}

    def value_type(self, name: str) -> pa.DataType:
        return _value_type(string_to_type(self.columns[name]["type"]))

    def _stats(self, name: str) -> dict[str, Any]:
        stats: dict[str, Any] = self.columns[name].get("stats", {})
        return stats

    def _has_histogram(self, name: str) -> bool:
        return "histogram" in self._stats(name)

    def _code_values(self, name: str) -> list[dict[str, Any]]:
        if self.columns[name]["role"] != "code":
            return []
        values: list[dict[str, Any]] = self._stats(name).get("values", [])
        return values

    def natural_size(self, name: str, fallback: int) -> int:
        if code_values := self._code_values(name):
            return len(code_values)
        distinct = self._stats(name).get("distinct_count")
        return max(1, int(distinct) if distinct else fallback)

    def is_extensible(self, name: str) -> bool:
        return not self._code_values(name)

    def domain(self, name: str, size: int) -> list[Any]:
        if name not in self._domains:
            self._domains[name] = self._make_domain(name, size)
        return self._domains[name]

    def _make_domain(self, name: str, size: int) -> list[Any]:
        value_type = self.value_type(name)
        if code_values := self._code_values(name):
            return [_from_json(item["value"], value_type) for item in code_values]
        if self.columns[name]["role"] == "code":
            raise ValueError(
                "A code column has no approved values after suppression; change its role or review k"
            )
        if self._has_histogram(name):
            values: list[Any] = []
            for _ in range(20):
                values = list(dict.fromkeys(values + self._numeric(name, size)))
                if len(values) >= size:
                    break
            return values[:size]
        if self.columns[name]["role"] == "pattern":
            return self._pattern_domain(name, size)
        return _schema_only_domain(name, value_type, size)

    def _pattern_domain(self, name: str, size: int) -> list[Any]:
        stats = self._stats(name)
        alphabets = {
            "digit": string.digits,
            "upper": string.ascii_uppercase,
            "lower": string.ascii_lowercase,
            "space": " ",
            "other": "-_",
        }
        alphabet = "".join(alphabets[key] for key in stats.get("character_classes", []))
        if not alphabet:
            return [""]
        length = stats.get("min_length", 0)
        maximum = stats.get("max_length", length)
        while len(alphabet) ** length < size and length < maximum:
            length += 1
        capacity = len(alphabet) ** length
        size = min(size, capacity)
        # A seeded alphabet permutation and offset produce distinct strings without
        # rejection loops, including when a small pattern domain is nearly full.
        characters = [alphabet[index] for index in self.rng.permutation(len(alphabet))]
        offset = int(self.rng.integers(0, min(capacity, 2**63 - 1)))
        values = []
        for index in range(size):
            number = (index + offset) % capacity
            encoded = []
            for _ in range(length):
                number, digit = divmod(number, len(characters))
                encoded.append(characters[digit])
            values.append("".join(encoded))
        return values

    def unique_rows(self, names: list[str], n: int) -> dict[str, list[Any]]:
        fallback = max(2, math.ceil(n ** (1 / len(names))))
        sizes = [self.natural_size(name, fallback) for name in names]
        extensible = [i for i, name in enumerate(names) if self.is_extensible(name)]
        if extensible and math.prod(sizes) < n:
            factor = (n / math.prod(sizes)) ** (1 / len(extensible))
            for i in extensible:
                sizes[i] = math.ceil(sizes[i] * factor)
        domains = [
            self.domain(name, size) for name, size in zip(names, sizes, strict=True)
        ]
        sizes = [len(domain) for domain in domains]
        total = math.prod(sizes)
        if total < n:
            raise ValueError(
                "Insufficient unique key capacity for the requested row count"
            )
        if total <= 2 * n:
            combos = list(itertools.product(*(range(size) for size in sizes)))
            chosen = sorted(self.rng.permutation(len(combos))[:n].tolist())
            rows = [combos[index] for index in chosen]
        else:
            seen: dict[tuple[int, ...], None] = {}
            while len(seen) < n:
                batch = np.stack(
                    [self.rng.integers(0, size, n) for size in sizes], axis=1
                )
                for row in map(tuple, batch.tolist()):
                    seen.setdefault(row, None)
                    if len(seen) == n:
                        break
            rows = sorted(seen)
        return {
            name: [domains[i][row[i]] for row in rows] for i, name in enumerate(names)
        }

    def sample(self, name: str, n: int) -> list[Any]:
        if code_values := self._code_values(name):
            weights = np.array([item["count"] for item in code_values], dtype=float)
            domain = self.domain(name, len(code_values))
            indices = self.rng.choice(len(domain), n, p=weights / weights.sum())
            values = [domain[index] for index in indices]
        elif self._has_histogram(name):
            values = self._numeric(name, n)
        else:
            domain = self.domain(name, self.natural_size(name, min(max(n, 1), 100)))
            values = [domain[index] for index in self.rng.integers(0, len(domain), n)]
        return self._with_nulls(name, values)

    def derive(self, name: str, parent_values: list[Any], kind: str) -> list[Any]:
        distinct = list(dict.fromkeys(parent_values))
        if kind == "1:1":
            domain = self._make_domain(name, len(distinct))
            if len(domain) < len(distinct):
                raise ValueError("Insufficient unique values for a 1:1 mapping")
            mapping = {value: domain[index] for index, value in enumerate(distinct)}
        else:
            mapping = dict(zip(distinct, self.sample(name, len(distinct)), strict=True))
        return [mapping[value] for value in parent_values]

    def random_walk(self, name: str, n_series: int, n_periods: int) -> list[Any]:
        stats = self._stats(name)
        if self._has_histogram(name):
            low, high = float(stats["min"]), float(stats["max"])
            start = self._numeric_floats(name, n_series)
        else:
            low, high = 0.0, 100.0
            start = self.rng.uniform(low, high, n_series)
        changes = self.rng.normal(0.0, RANDOM_WALK_STEP, (n_series, n_periods))
        changes[:, 0] = 0.0
        walk = start[:, None] * np.cumprod(1.0 + changes, axis=1)
        walk = np.clip(walk, low, high)
        return self._with_nulls(name, self._to_python(name, walk.ravel()))

    def _numeric_floats(self, name: str, n: int) -> npt.NDArray[np.float64]:
        stats = self._stats(name)
        edges = np.array(stats["histogram"]["edges"], dtype=float)
        fractions = np.array(stats["histogram"]["fractions"], dtype=float)
        bins = self.rng.choice(len(fractions), n, p=fractions / fractions.sum())
        values = self.rng.uniform(edges[bins], edges[bins + 1])
        clipped = np.clip(values, float(stats["min"]), float(stats["max"]))
        return cast("npt.NDArray[np.float64]", clipped)

    def _numeric(self, name: str, n: int) -> list[Any]:
        return self._to_python(name, self._numeric_floats(name, n))

    def _to_python(self, name: str, values: npt.NDArray[np.float64]) -> list[Any]:
        value_type = self.value_type(name)
        if pa.types.is_integer(value_type):
            info = np.iinfo(cast("Any", value_type.to_pandas_dtype()))
            return [
                min(int(info.max), max(int(info.min), round(float(value))))
                for value in values
            ]
        if pa.types.is_decimal(value_type):
            with localcontext() as context:
                context.prec = value_type.precision + abs(value_type.scale) + 4
                quantum = Decimal(1).scaleb(-value_type.scale)
                limit = (Decimal(10) ** value_type.precision - 1) * quantum
                return [
                    min(
                        limit, max(-limit, Decimal(str(float(value))).quantize(quantum))
                    )
                    for value in values
                ]
        return [float(value) for value in values]

    def _with_nulls(self, name: str, values: list[Any]) -> list[Any]:
        null_fraction = float(self._stats(name).get("null_fraction", 0.0))
        if not self.columns[name]["nullable"] or null_fraction <= 0:
            return values
        mask = self.rng.random(len(values)) < null_fraction
        return [None if is_null else v for v, is_null in zip(values, mask, strict=True)]


def _schema_only_domain(name: str, value_type: pa.DataType, size: int) -> list[Any]:
    if _is_string(value_type):
        width = len(str(size))
        return [f"{name}_{index:0{width}d}" for index in range(1, size + 1)]
    if pa.types.is_boolean(value_type):
        return [False, True][:size]
    if pa.types.is_integer(value_type):
        upper = int(np.iinfo(cast("Any", value_type.to_pandas_dtype())).max)
        return list(range(min(size, upper + 1)))
    if pa.types.is_floating(value_type):
        return [float(index) for index in range(size)]
    if pa.types.is_decimal(value_type):
        with localcontext() as context:
            context.prec = value_type.precision + abs(value_type.scale) + 4
            return [
                Decimal(index).scaleb(-value_type.scale)
                for index in range(min(size, 10**value_type.precision))
            ]
    if pa.types.is_timestamp(value_type):
        return [datetime(2000, 1, 1) + timedelta(hours=i) for i in range(size)]
    return [date(2000, 1, 1) + timedelta(days=index) for index in range(size)]

"""Validation of local JSON documents without echoing their contents."""

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa


def read_json(path: Path) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON contains duplicate keys")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError("JSON contains a non-finite number")

    try:
        result = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=invalid_constant,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(
            "Invalid JSON document; check its syntax and UTF-8 encoding"
        ) from exc
    if not isinstance(result, dict):
        raise ValueError("JSON document must be an object")
    return result


def integer(value: Any, label: str, minimum: int, maximum: int | None = None) -> None:
    if (
        type(value) is not int
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        suffix = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(f"{label} must be an integer >= {minimum}{suffix}")


def number(
    value: Any, label: str, minimum: float | None = None, maximum: float | None = None
) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if (minimum is not None and value < minimum) or (
        maximum is not None and value > maximum
    ):
        raise ValueError(f"{label} is outside its allowed range")


def names(value: Any, label: str, allowed: list[str], *, empty: bool = True) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of column names")
    if len(set(value)) != len(value) or any(item not in allowed for item in value):
        raise ValueError(f"{label} contains duplicate or unknown column names")
    if not empty and not value:
        raise ValueError(f"{label} must not be empty")


def config_shape(config: dict[str, Any], allowed: list[str]) -> None:
    integer(config["k"], "k", 1)
    integer(config["significant_digits"], "significant_digits", 1, 15)
    integer(config["max_key_size"], "max_key_size", 1, 5)
    integer(config["mapping_max_distinct"], "mapping_max_distinct", 1)
    if not isinstance(config["columns"], dict):
        raise ValueError("columns must be an object mapping column names to roles")
    names(config["force_code"], "force_code", allowed)
    setting = config["timeseries"]
    if isinstance(setting, str) and setting in ("auto", "none"):
        return
    if not isinstance(setting, dict) or set(setting) != {
        "period",
        "series_keys",
        "values",
    }:
        raise ValueError(
            "timeseries must be 'auto', 'none' or an object with period, series_keys and values"
        )
    if not isinstance(setting["period"], str) or setting["period"] not in allowed:
        raise ValueError("timeseries period must name an existing column")
    names(setting["series_keys"], "series_keys", allowed)
    names(setting["values"], "values", allowed, empty=False)
    roles = [setting["period"], *setting["series_keys"], *setting["values"]]
    if len(set(roles)) != len(roles):
        raise ValueError("Time-series roles must not overlap")


def profile_shape(
    profile: dict[str, Any], parse_type: Callable[[str], pa.DataType]
) -> None:
    integer(profile.get("format_version"), "format_version", 1)
    if profile["format_version"] != 1:
        raise ValueError(
            "Unsupported profile format version; use a compatible synthparq release"
        )
    features = profile.get("required_features", [])
    if not isinstance(features, list) or features:
        raise ValueError(
            "Unsupported required profile features; use a compatible synthparq release"
        )
    integer(profile.get("row_count"), "row_count", 0)
    columns = profile.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ValueError("Profile columns must be a non-empty list")
    allowed: list[str] = []
    for column in columns:
        if not isinstance(column, dict) or not isinstance(column.get("name"), str):
            raise ValueError("Each profile column must have a name")
        name = column["name"]
        if name in allowed:
            raise ValueError("Profile has duplicate column names")
        allowed.append(name)
        if (
            not isinstance(column.get("type"), str)
            or type(column.get("nullable")) is not bool
        ):
            raise ValueError(
                "Each profile column must have a type and boolean nullable flag"
            )
        data_type = parse_type(column["type"])
        if pa.types.is_dictionary(data_type):
            data_type = data_type.value_type
        role = column.get("role")
        if role not in ("schema_only", "pattern", "code", "numeric_stats"):
            raise ValueError("Invalid profile column role")
        if role == "pattern" and not (
            pa.types.is_string(data_type) or pa.types.is_large_string(data_type)
        ):
            raise ValueError("Pattern role requires a string type")
        if role == "numeric_stats" and not (
            pa.types.is_integer(data_type)
            or pa.types.is_floating(data_type)
            or pa.types.is_decimal(data_type)
        ):
            raise ValueError("numeric_stats role requires a numeric type")
        stats = column.get("stats", {})
        if not isinstance(stats, dict):
            raise ValueError("Profile statistics must be an object")
        if role == "schema_only" and stats:
            raise ValueError("schema_only columns must not contain statistics")
        _stats_shape(stats, role)
    if profile.get("primary_key") is not None:
        names(profile["primary_key"], "primary_key", allowed, empty=False)
    mappings = profile.get("mappings", [])
    if not isinstance(mappings, list):
        raise ValueError("mappings must be a list")
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != {"from", "to", "kind"}:
            raise ValueError("Invalid mapping definition")
        names([mapping["from"], mapping["to"]], "mapping endpoints", allowed)
        if mapping["kind"] not in ("1:1", "N:1"):
            raise ValueError("Mapping kind must be 1:1 or N:1 (many -> one)")
    timeseries = profile.get("timeseries")
    if timeseries is not None:
        required = {
            "period",
            "period_format",
            "frequency",
            "start",
            "end",
            "series_keys",
            "values",
            "n_series",
        }
        if not isinstance(timeseries, dict) or set(timeseries) != required:
            raise ValueError("Invalid time-series definition")
        config_shape(
            {
                "k": 1,
                "significant_digits": 3,
                "max_key_size": 5,
                "mapping_max_distinct": 1,
                "columns": {},
                "force_code": [],
                "timeseries": {
                    key: timeseries[key] for key in ("period", "series_keys", "values")
                },
            },
            allowed,
        )
        if timeseries["frequency"] not in ("Y", "Q", "M", "D"):
            raise ValueError("Unsupported time-series frequency")
        if not all(
            isinstance(timeseries[key], str)
            for key in ("start", "end", "period_format")
        ):
            raise ValueError("Invalid time-series period metadata")
        integer(timeseries["n_series"], "n_series", 1)
        for column in columns:
            if column["name"] in timeseries["values"]:
                value_type = parse_type(column["type"])
                if pa.types.is_dictionary(value_type):
                    value_type = value_type.value_type
                if not (
                    pa.types.is_integer(value_type)
                    or pa.types.is_floating(value_type)
                    or pa.types.is_decimal(value_type)
                ):
                    raise ValueError("Time-series values must be numeric")


def _stats_shape(stats: dict[str, Any], role: str) -> None:
    number(stats.get("null_fraction", 0), "null_fraction", 0, 1)
    if "distinct_count" in stats:
        integer(stats["distinct_count"], "distinct_count", 0)
    if role == "code":
        values = stats.get("values")
        if not isinstance(values, list):
            raise ValueError("Code statistics require a values list")
        for item in values:
            if (
                not isinstance(item, dict)
                or set(item) != {"value", "count"}
                or item["value"] is None
            ):
                raise ValueError("Invalid code value entry")
            integer(item["count"], "code count", 1)
        number(stats.get("suppressed_fraction", 0), "suppressed_fraction", 0, 1)
    if role == "pattern" and "min_length" in stats:
        integer(stats["min_length"], "min_length", 0)
        integer(stats.get("max_length"), "max_length", stats["min_length"])
        classes = stats.get("character_classes")
        if not isinstance(classes, list) or any(
            c not in ("digit", "upper", "lower", "space", "other") for c in classes
        ):
            raise ValueError("Invalid pattern character classes")
    if "histogram" in stats:
        histogram = stats["histogram"]
        if not isinstance(histogram, dict) or set(histogram) != {"edges", "fractions"}:
            raise ValueError("Invalid histogram")
        edges, fractions = histogram["edges"], histogram["fractions"]
        if (
            not isinstance(edges, list)
            or not isinstance(fractions, list)
            or not fractions
            or len(edges) != len(fractions) + 1
        ):
            raise ValueError("Invalid histogram dimensions")
        for edge in edges:
            number(edge, "histogram edge")
        if edges != sorted(edges):
            raise ValueError("Histogram edges must be ordered")
        for fraction in fractions:
            number(fraction, "histogram fraction", 0, 1)
        if sum(fractions) <= 0:
            raise ValueError("Histogram fractions must have positive mass")
        number(stats.get("min"), "minimum")
        number(stats.get("max"), "maximum", stats["min"])

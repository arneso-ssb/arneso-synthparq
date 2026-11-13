import json
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from click.testing import CliRunner

from synthparq import generate_parquet
from synthparq import init_config
from synthparq import profile_parquet
from synthparq import string_to_type
from synthparq import type_to_string
from synthparq.__main__ import main

COMPANIES = {
    "9100000001": "Secret Bank Alpha",
    "9100000002": "Secret Bank Beta",
    "9100000003": "Secret Bank Gamma",
    "9100000004": "Secret Bank Delta",
}
SERIES = {"LOAN_A": "L", "LOAN_B": "L", "DEPOSIT_A": "D"}
PERIODS = ["202501", "202502", "202503", "202504", "202505", "202506"]


def _timeseries_table() -> pa.Table:
    rows: dict[str, list[Any]] = {
        name: []
        for name in [
            "periode",
            "selskap",
            "selskapsnavn",
            "Serienavn",
            "kind",
            "rente",
            "belop",
        ]
    }
    value = 0
    for company, company_name in COMPANIES.items():
        for series, kind in SERIES.items():
            for period in PERIODS:
                value += 1
                rows["periode"].append(period)
                rows["selskap"].append(company)
                rows["selskapsnavn"].append(company_name)
                rows["Serienavn"].append(series)
                rows["kind"].append(kind)
                rows["rente"].append(1.5 + (value % 7) / 10)
                rows["belop"].append(Decimal(f"{1000 + value * 13}.25"))
    schema = pa.schema(
        cast(
            "list[pa.Field[Any]]",
            [
                pa.field("periode", pa.large_string()),
                pa.field("selskap", pa.large_string()),
                pa.field("selskapsnavn", pa.large_string()),
                pa.field("Serienavn", pa.dictionary(pa.int8(), pa.string())),
                pa.field("kind", pa.string()),
                pa.field("rente", pa.float64()),
                pa.field("belop", pa.decimal128(12, 2)),
            ],
        )
    )
    return pa.Table.from_pydict(rows, schema=schema)


def _write_config(path: Path, columns: dict[str, str], **extra: Any) -> Path:
    path.write_text(json.dumps({"columns": columns, **extra}), encoding="utf-8")
    return path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.parquet"
    pq.write_table(_timeseries_table(), path)
    return path


@pytest.fixture
def config(tmp_path: Path) -> Path:
    return _write_config(
        tmp_path / "export.json",
        {
            "periode": "code",
            "selskap": "pattern",
            "selskapsnavn": "pattern",
            "Serienavn": "code",
            "kind": "code",
            "rente": "numeric_stats",
            "belop": "numeric_stats",
        },
    )


@pytest.mark.parametrize(
    "data_type",
    [
        pa.bool_(),
        pa.int8(),
        pa.uint64(),
        pa.float32(),
        pa.float64(),
        pa.string(),
        pa.large_string(),
        pa.date32(),
        pa.timestamp("us"),
        pa.timestamp("ns", tz="Europe/Oslo"),
        pa.decimal128(12, 2),
        pa.decimal256(40, 10),
        pa.dictionary(pa.int8(), pa.string()),
        pa.dictionary(pa.int16(), pa.timestamp("ms", tz="UTC"), ordered=True),
    ],
)
def test_type_strings_round_trip(data_type: pa.DataType) -> None:
    assert string_to_type(type_to_string(data_type)) == data_type


def test_type_strings_are_readable() -> None:
    assert type_to_string(pa.decimal128(12, 2)) == "decimal128(12, 2)"
    assert (
        type_to_string(pa.timestamp("us", tz="Europe/Oslo"))
        == "timestamp[us, tz=Europe/Oslo]"
    )
    assert (
        type_to_string(pa.dictionary(pa.int8(), pa.string()))
        == "dictionary<int8, string>"
    )


def test_unsupported_types_fail() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        type_to_string(pa.list_(pa.int64()))
    with pytest.raises(ValueError, match="Unsupported"):
        string_to_type("list<int64>")


def test_init_config_lists_all_columns_as_schema_only(
    source: Path, tmp_path: Path
) -> None:
    config_file = init_config(source, tmp_path / "export.json")

    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert config["columns"] == dict.fromkeys(
        _timeseries_table().column_names, "schema_only"
    )


def test_profile_without_config_exports_no_values(source: Path, tmp_path: Path) -> None:
    profile_file = profile_parquet(source, tmp_path / "profile.json")

    text = profile_file.read_text(encoding="utf-8")
    profile = json.loads(text)
    assert all("stats" not in column for column in profile["columns"])
    for company, name in COMPANIES.items():
        assert company not in text
        assert name not in text
    assert "LOAN_A" not in text


def test_profile_never_exports_raw_values_of_pattern_columns(
    source: Path, config: Path, tmp_path: Path
) -> None:
    text = profile_parquet(source, tmp_path / "profile.json", config).read_text(
        encoding="utf-8"
    )

    for company, name in COMPANIES.items():
        assert company not in text
        assert name not in text


def test_exported_codes_occur_at_least_k_times(tmp_path: Path) -> None:
    table = pa.table({"code": ["common"] * 6 + ["rare"] * 4 + ["other"] * 10})
    source = tmp_path / "codes.parquet"
    pq.write_table(table, source)
    config = _write_config(tmp_path / "export.json", {"code": "code"}, k=5)

    profile = json.loads(
        profile_parquet(source, tmp_path / "profile.json", config).read_text(
            encoding="utf-8"
        )
    )

    values = table.column("code").to_pylist()
    exported = [v["value"] for v in profile["columns"][0]["stats"]["values"]]
    assert set(exported) == {"common", "other"}
    assert all(values.count(value) >= 5 for value in exported)


def test_small_histogram_bins_are_merged(tmp_path: Path) -> None:
    table = pa.table({"x": [0.0] * 20 + [100.0]})
    source = tmp_path / "x.parquet"
    pq.write_table(table, source)
    config = _write_config(tmp_path / "export.json", {"x": "numeric_stats"}, k=5)

    profile = json.loads(
        profile_parquet(source, tmp_path / "profile.json", config).read_text(
            encoding="utf-8"
        )
    )

    fractions = profile["columns"][0]["stats"]["histogram"]["fractions"]
    assert all(fraction * 21 >= 5 for fraction in fractions)


def test_config_with_unknown_column_fails(source: Path, tmp_path: Path) -> None:
    config = _write_config(tmp_path / "export.json", {"no_such_column": "code"})

    with pytest.raises(ValueError, match="no_such_column"):
        profile_parquet(source, tmp_path / "profile.json", config)


def test_config_with_missing_column_warns(source: Path, tmp_path: Path) -> None:
    config = _write_config(tmp_path / "export.json", {"periode": "code"})

    with pytest.warns(UserWarning, match="selskap"):
        profile_parquet(source, tmp_path / "profile.json", config)


def test_id_like_code_column_fails_unless_forced(source: Path, tmp_path: Path) -> None:
    table = pa.table({"id": [f"{i:04d}" for i in range(20)]})
    source = tmp_path / "ids.parquet"
    pq.write_table(table, source)

    with pytest.raises(ValueError, match="identifier"):
        profile_parquet(
            source,
            tmp_path / "profile.json",
            _write_config(tmp_path / "export.json", {"id": "code"}, k=1),
        )

    profile_parquet(
        source,
        tmp_path / "profile.json",
        _write_config(tmp_path / "forced.json", {"id": "code"}, k=1, force_code=["id"]),
    )


def test_profile_detects_key_mappings_and_timeseries(
    source: Path, config: Path, tmp_path: Path
) -> None:
    profile = json.loads(
        profile_parquet(source, tmp_path / "profile.json", config).read_text(
            encoding="utf-8"
        )
    )

    assert sorted(profile["primary_key"]) == ["Serienavn", "periode", "selskap"]
    assert {"from": "selskap", "to": "selskapsnavn", "kind": "1:1"} in profile[
        "mappings"
    ]
    assert {"from": "Serienavn", "to": "kind", "kind": "N:1"} in profile["mappings"]
    timeseries = profile["timeseries"]
    assert timeseries["period"] == "periode"
    assert timeseries["frequency"] == "M"
    assert (timeseries["start"], timeseries["end"]) == ("202501", "202506")
    assert sorted(timeseries["series_keys"]) == ["Serienavn", "selskap"]
    assert sorted(timeseries["values"]) == ["belop", "rente"]


def _generate(source: Path, config: Path, tmp_path: Path, seed: int = 1) -> pa.Table:
    profile_file = profile_parquet(
        source, tmp_path / "profile.json", config, overwrite=True
    )
    output = generate_parquet(profile_file, tmp_path / f"out{seed}.parquet", seed=seed)
    return pq.read_table(output)


def test_generated_data_preserves_schema_keys_and_mappings(
    source: Path, config: Path, tmp_path: Path
) -> None:
    original = _timeseries_table()

    synthetic = _generate(source, config, tmp_path)

    assert synthetic.schema.remove_metadata() == original.schema.remove_metadata()
    rows = synthetic.to_pylist()
    keys = [(r["periode"], r["selskap"], r["Serienavn"]) for r in rows]
    assert len(set(keys)) == len(keys)
    for determinant, dependent in [("selskap", "selskapsnavn"), ("Serienavn", "kind")]:
        pairs = {(r[determinant], r[dependent]) for r in rows}
        assert len(pairs) == len({r[determinant] for r in rows})
    names = {r["selskapsnavn"] for r in rows}
    assert len(names) == len({r["selskap"] for r in rows})


def test_generated_timeseries_covers_all_periods(
    source: Path, config: Path, tmp_path: Path
) -> None:
    synthetic = _generate(source, config, tmp_path)

    series: dict[tuple[str, str], list[str]] = {}
    for row in synthetic.to_pylist():
        series.setdefault((row["selskap"], row["Serienavn"]), []).append(row["periode"])
    assert all(sorted(periods) == PERIODS for periods in series.values())
    rente = cast("list[float]", synthetic.column("rente").to_pylist())
    assert all(1.4 <= value <= 2.2 for value in rente)


def test_generated_values_change_smoothly_within_a_series(
    source: Path, config: Path, tmp_path: Path
) -> None:
    synthetic = _generate(source, config, tmp_path)

    rows = synthetic.to_pylist()
    first = [
        r
        for r in rows
        if (r["selskap"], r["Serienavn"])
        == (
            rows[0]["selskap"],
            rows[0]["Serienavn"],
        )
    ]
    values = [float(r["belop"]) for r in sorted(first, key=lambda r: r["periode"])]
    belop = [
        float(v) for v in cast("list[Decimal]", synthetic.column("belop").to_pylist())
    ]
    span = max(belop) - min(belop)
    assert all(abs(b - a) <= span / 2 for a, b in pairwise(values))


def test_generation_is_deterministic(
    source: Path, config: Path, tmp_path: Path
) -> None:
    profile_file = profile_parquet(source, tmp_path / "profile.json", config)

    first = generate_parquet(profile_file, tmp_path / "a.parquet", seed=7)
    second = generate_parquet(profile_file, tmp_path / "b.parquet", seed=7)

    assert pq.read_table(first).equals(pq.read_table(second))


def test_generate_respects_requested_row_count(
    source: Path, config: Path, tmp_path: Path
) -> None:
    profile_file = profile_parquet(source, tmp_path / "profile.json", config)

    output = generate_parquet(profile_file, tmp_path / "out.parquet", n_rows=600)

    synthetic = pq.read_table(output)
    assert synthetic.num_rows >= 600
    assert synthetic.num_rows % len(PERIODS) == 0


def test_generation_from_schema_only_profile(source: Path, tmp_path: Path) -> None:
    profile_file = profile_parquet(source, tmp_path / "profile.json")

    output = generate_parquet(profile_file, tmp_path / "out.parquet")

    synthetic = pq.read_table(output)
    original = _timeseries_table()
    assert synthetic.schema.remove_metadata() == original.schema.remove_metadata()
    assert synthetic.num_rows > 0


def test_non_timeseries_table_round_trip(tmp_path: Path) -> None:
    table = pa.table(
        {
            "id": pa.array(range(50), type=pa.int32()),
            "when": pa.array(
                [None] * 10 + [1_700_000_000_000_000] * 40,
                type=pa.timestamp("us", tz="Europe/Oslo"),
            ),
            "flag": [True, False] * 25,
        }
    )
    source = tmp_path / "plain.parquet"
    pq.write_table(table, source)

    profile_file = profile_parquet(source, tmp_path / "profile.json")
    synthetic = pq.read_table(generate_parquet(profile_file, tmp_path / "out.parquet"))

    profile = json.loads(profile_file.read_text(encoding="utf-8"))
    assert profile["primary_key"] == ["id"]
    assert profile["timeseries"] is None
    assert synthetic.schema.remove_metadata() == table.schema
    ids = synthetic.column("id").to_pylist()
    assert len(set(ids)) == len(ids) == 50


def test_cli_profile_and_generate(source: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    config_file = tmp_path / "export.json"
    profile_file = tmp_path / "profile.json"
    output = tmp_path / "synthetic.parquet"

    init = runner.invoke(
        main, ["profile", str(source), "--init-config", str(config_file)]
    )
    exported = runner.invoke(
        main,
        [
            "profile",
            str(source),
            "--config",
            str(config_file),
            "--out",
            str(profile_file),
        ],
    )
    generated = runner.invoke(
        main,
        ["generate", str(profile_file), "--out", str(output), "--seed", "3"],
    )

    assert (init.exit_code, exported.exit_code, generated.exit_code) == (0, 0, 0)
    assert pq.read_table(output).num_rows > 0

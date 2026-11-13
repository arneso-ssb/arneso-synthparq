"""Safety contracts at the public API and CLI boundaries."""

import json
from datetime import datetime
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from click.testing import CliRunner

from synthparq import generate_parquet
from synthparq import init_config
from synthparq import profile_parquet
from synthparq.__main__ import main


def test_cli_version_uses_distribution_name() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert version("arneso-synthparq") in result.output


def test_outputs_require_explicit_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": range(10)}), source)
    config = init_config(source, tmp_path / "export.json")
    original = config.read_bytes()
    with pytest.raises(FileExistsError):
        init_config(source, config)
    assert config.read_bytes() == original
    init_config(source, config, overwrite=True)
    profile = profile_parquet(source, tmp_path / "profile.json", config)
    with pytest.raises(FileExistsError):
        profile_parquet(source, profile, config)
    output = generate_parquet(profile, tmp_path / "output.parquet")
    with pytest.raises(FileExistsError):
        generate_parquet(profile, output)
    generate_parquet(profile, output, overwrite=True)


def test_cli_errors_do_not_print_tracebacks(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": range(10)}), source)
    target = tmp_path / "export.json"
    target.write_text("keep me", encoding="utf-8")
    result = CliRunner().invoke(
        main, ["profile", str(source), "--init-config", str(target)]
    )
    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "Traceback" not in result.output
    assert target.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize(
    "setting",
    [
        {"k": 0},
        {"k": True},
        {"k": 2.5},
        {"significant_digits": 0},
        {"significant_digits": 20},
        {"max_key_size": 6},
        {"mapping_max_distinct": -1},
        {"force_code": "id"},
        {"columns": []},
        {"timeseries": {"period": "id"}},
        {"typo": True},
    ],
)
def test_invalid_config_fails_before_reading_rows(
    tmp_path: Path, setting: dict[str, Any]
) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": range(10)}), source)
    config = tmp_path / "export.json"
    config.write_text(json.dumps({"columns": {"id": "schema_only"}, **setting}))
    output = tmp_path / "profile.json"
    with patch.object(pq, "read_table", side_effect=AssertionError("read rows")):
        with pytest.raises(ValueError):
            profile_parquet(source, output, config)
    assert not output.exists()


def test_init_config_never_reads_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": range(10)}), source)
    with patch.object(pq, "read_table", side_effect=AssertionError("read rows")):
        init_config(source, tmp_path / "export.json")


def test_no_config_still_exports_reviewable_dataset_metadata(tmp_path: Path) -> None:
    source = tmp_path / "private-filename.parquet"
    pq.write_table(
        pa.table({"periode": ["202501", "202502"], "amount": [1.0, 2.0]}), source
    )
    path = profile_parquet(source, tmp_path / "profile.json")
    profile = json.loads(path.read_text())
    assert profile["row_count"] == 2
    assert profile["primary_key"] == ["periode"]
    assert profile["timeseries"]["start"] == "202501"
    assert all("stats" not in column for column in profile["columns"])
    assert "private-filename" not in path.read_text()
    assert profile["producer"]["name"] == "arneso-synthparq"


def test_null_column_cannot_be_a_primary_key(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": [1, 2, None]}), source)
    profile = json.loads(profile_parquet(source, tmp_path / "profile.json").read_text())
    assert profile["primary_key"] is None


def test_impossible_key_size_never_returns_fewer_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": ["a", "b", "c"]}), source)
    config = tmp_path / "export.json"
    config.write_text(
        json.dumps({"k": 1, "force_code": ["id"], "columns": {"id": "code"}})
    )
    profile = profile_parquet(source, tmp_path / "profile.json", config)
    output = tmp_path / "output.parquet"
    with pytest.raises(ValueError, match=r"unique|capacity"):
        generate_parquet(profile, output, n_rows=4)
    assert not output.exists()


def test_overlapping_dependencies_are_all_preserved(tmp_path: Path) -> None:
    # Diamond: A determines B and C; both B and C determine D.
    source = tmp_path / "source.parquet"
    pq.write_table(
        pa.table(
            {
                "A": ["a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7"] * 10,
                "B": ["b0", "b0", "b1", "b1", "b2", "b2", "b3", "b3"] * 10,
                "C": ["c0", "c1", "c0", "c1", "c2", "c3", "c2", "c3"] * 10,
                "D": ["d0"] * 4 * 1 + ["d1"] * 4 + (["d0"] * 4 + ["d1"] * 4) * 9,
            }
        ),
        source,
    )
    profile_path = profile_parquet(source, tmp_path / "profile.json")
    profile = json.loads(profile_path.read_text())
    assert {"from": "B", "to": "D", "kind": "N:1"} in profile["mappings"]
    assert {"from": "C", "to": "D", "kind": "N:1"} in profile["mappings"]
    output = generate_parquet(profile_path, tmp_path / "output.parquet", n_rows=100)
    rows = pq.read_table(output).to_pylist()
    for relation in profile["mappings"]:
        a, b = relation["from"], relation["to"]
        pairs = {(row[a], row[b]) for row in rows}
        assert len(pairs) == len({row[a] for row in rows})
        if relation["kind"] == "1:1":
            assert len(pairs) == len({row[b] for row in rows})


def test_empty_code_allow_list_cannot_invent_values(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"code": ["rare"] * 3}), source)
    config = tmp_path / "export.json"
    config.write_text(json.dumps({"columns": {"code": "code"}}))
    profile = profile_parquet(source, tmp_path / "profile.json", config)
    with pytest.raises(ValueError, match=r"code|approved"):
        generate_parquet(profile, tmp_path / "output.parquet")


@pytest.mark.parametrize(
    "update",
    [
        {"format_version": True},
        {"format_version": 999},
        {"row_count": -1},
        {"row_count": True},
        {"columns": []},
        {"primary_key": ["missing"]},
        {"mappings": [{"from": "id", "to": "missing", "kind": "N:1"}]},
        {"required_features": ["unknown-future-feature"]},
        {"timeseries": {"period": "id"}},
    ],
)
def test_invalid_profile_is_rejected_cleanly(
    tmp_path: Path, update: dict[str, Any]
) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": range(10)}), source)
    path = profile_parquet(source, tmp_path / "profile.json")
    profile = json.loads(path.read_text())
    path.write_text(json.dumps({**profile, **update}))
    output = tmp_path / "output.parquet"
    result = CliRunner().invoke(main, ["generate", str(path), "--out", str(output)])
    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "Traceback" not in result.output
    assert not output.exists()


def test_profile_compatibility_is_not_tied_to_producer_version(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "profile-v1.json"
    output = generate_parquet(fixture, tmp_path / "output.parquet")
    table = pq.read_table(output)
    assert table.num_rows == 6
    assert table.column_names == ["id", "amount"]
    assert table.schema.field("amount").type == pa.decimal128(12, 2)


@pytest.mark.parametrize("rows", [-1])
def test_python_api_rejects_invalid_row_counts(tmp_path: Path, rows: int) -> None:
    fixture = Path(__file__).parent / "fixtures" / "profile-v1.json"
    with pytest.raises(ValueError):
        generate_parquet(fixture, tmp_path / "output.parquet", n_rows=rows)


@pytest.mark.parametrize(
    "data_type,values",
    [
        (
            pa.decimal256(60, 10),
            [Decimal("1.2345678901E+40"), Decimal("2.3456789012E+40")] * 5,
        ),
        (
            pa.decimal128(38, 2),
            [Decimal("999999999999999999999999999999999999.98")] * 10,
        ),
        (pa.decimal128(3, 3), [Decimal("0.998"), Decimal("0.999")] * 5),
        (pa.uint64(), [2**64 - 2, 2**64 - 1] * 5),
    ],
)
def test_numeric_boundaries_generate_representable_values(
    tmp_path: Path, data_type: pa.DataType, values: list[Any]
) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"amount": pa.array(values, type=data_type)}), source)
    config = tmp_path / "export.json"
    config.write_text(
        json.dumps({"columns": {"amount": "numeric_stats"}, "timeseries": "none"})
    )
    profile = profile_parquet(source, tmp_path / "profile.json", config)
    output = generate_parquet(profile, tmp_path / "output.parquet", n_rows=20)
    table = pq.read_table(output)
    assert table.schema.field("amount").type == data_type
    assert table.num_rows == 20


def test_timestamp_series_preserves_local_midnight(tmp_path: Path) -> None:
    zone = ZoneInfo("Europe/Oslo")
    source = tmp_path / "source.parquet"
    dates = [datetime(2025, month, 1, tzinfo=zone) for month in (1, 2, 3, 4)]
    pq.write_table(
        pa.table(
            {
                "period": pa.array(dates, type=pa.timestamp("us", tz="Europe/Oslo")),
                "amount": [1.0] * 4,
            }
        ),
        source,
    )
    profile = profile_parquet(source, tmp_path / "profile.json")
    output = generate_parquet(profile, tmp_path / "output.parquet")
    assert pq.read_table(output).column("period").to_pylist() == dates


def test_existing_source_cannot_be_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": range(10)}), source)
    original = source.read_bytes()
    with pytest.raises(ValueError, match="different"):
        profile_parquet(source, source, overwrite=True)
    assert source.read_bytes() == original


def test_code_diagnostics_do_not_echo_source_values(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    secret = "PRIVATE-EXAMPLE-VALUE"
    pq.write_table(pa.table({"amount": [secret]}), source)
    config = tmp_path / "export.json"
    config.write_text(json.dumps({"columns": {"amount": "numeric_stats"}}))
    result = CliRunner().invoke(
        main,
        [
            "profile",
            str(source),
            "--config",
            str(config),
            "--out",
            str(tmp_path / "profile.json"),
        ],
    )
    assert result.exit_code != 0
    assert secret not in result.output


def test_pattern_generation_respects_length_and_character_classes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"label": ["ABCD", "EFGH", "IJKL"] * 10}), source)
    config = tmp_path / "export.json"
    config.write_text(json.dumps({"columns": {"label": "pattern"}}))
    profile = profile_parquet(source, tmp_path / "profile.json", config)
    output = generate_parquet(profile, tmp_path / "output.parquet")
    values = pq.read_table(output).column("label").to_pylist()
    assert all(
        value is not None and len(value) == 4 and value.isalpha() and value.isupper()
        for value in values
    )


@pytest.mark.parametrize("order", [("parent", "child"), ("child", "parent")])
def test_mapping_direction_does_not_depend_on_column_order(
    tmp_path: Path, order: tuple[str, str]
) -> None:
    data = {"parent": ["a", "a", "b", "b"] * 3, "child": ["a1", "a2", "b1", "b2"] * 3}
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({name: data[name] for name in order}), source)
    profile = json.loads(profile_parquet(source, tmp_path / "profile.json").read_text())
    assert profile["mappings"] == [{"from": "child", "to": "parent", "kind": "N:1"}]


def test_invalid_code_values_produce_safe_cli_error(tmp_path: Path) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/profile-v1.json").read_text()
    )
    fixture["primary_key"] = None
    fixture["columns"][0].update(
        {
            "role": "code",
            "stats": {"values": [{"value": "SECRET-INVALID-INTEGER", "count": 6}]},
        }
    )
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(fixture))
    result = CliRunner().invoke(
        main, ["generate", str(profile), "--out", str(tmp_path / "out.parquet")]
    )
    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "SECRET-INVALID-INTEGER" not in result.output


def test_subdaily_timestamps_are_not_silently_truncated(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(
        pa.table(
            {
                "period": [datetime(2025, 1, 1, hour) for hour in range(4)],
                "value": [1.0] * 4,
            }
        ),
        source,
    )
    profile = json.loads(profile_parquet(source, tmp_path / "profile.json").read_text())
    assert profile["timeseries"] is None


def test_regular_periods_cannot_invent_unapproved_codes(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(
        pa.table({"period": ["202501", "202503"], "amount": [1.0, 2.0]}), source
    )
    config = tmp_path / "export.json"
    config.write_text(
        json.dumps(
            {
                "k": 1,
                "force_code": ["period"],
                "columns": {"period": "code", "amount": "schema_only"},
            }
        )
    )
    profile = profile_parquet(source, tmp_path / "profile.json", config)
    with pytest.raises(ValueError, match="approved"):
        generate_parquet(profile, tmp_path / "output.parquet")


def test_profile_and_generate_do_not_connect_to_network(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": range(10)}), source)
    with patch("socket.socket.connect", side_effect=AssertionError("network access")):
        profile = profile_parquet(source, tmp_path / "profile.json")
        output = generate_parquet(profile, tmp_path / "output.parquet")
    assert pq.read_table(output).num_rows == 10


def test_failed_write_preserves_existing_file_and_cleans_temporary(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "profile-v1.json"
    output = tmp_path / "output.parquet"
    output.write_bytes(b"original file")

    def failing_writer(table: pa.Table, path: Path) -> None:
        path.write_bytes(b"partial file")
        raise OSError("simulated full disk")

    with patch.object(pq, "write_table", side_effect=failing_writer):
        with pytest.raises(OSError, match="full disk"):
            generate_parquet(fixture, output, overwrite=True)
    assert output.read_bytes() == b"original file"
    assert list(tmp_path.iterdir()) == [output]

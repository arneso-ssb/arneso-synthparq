"""Create a tiny, wholly fabricated source table, config and profile.

Run with ``uv run python examples/create_example.py`` from the repository root.
No input data, environment credentials or production metadata are used.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from synthparq import init_config
from synthparq import profile_parquet


def main() -> None:
    """Rebuild the approved fabricated example artifacts."""
    directory = Path(__file__).resolve().parent
    rows: dict[str, list[Any]] = {
        name: []
        for name in ("period", "entity", "entity_name", "series", "kind", "amount")
    }
    for entity in range(1, 5):
        for series, kind in (("LOANS", "ASSET"), ("DEPOSITS", "LIABILITY")):
            for month in range(1, 7):
                rows["period"].append(f"2025{month:02d}")
                rows["entity"].append(f"DEMO{entity:04d}")
                rows["entity_name"].append(f"Fictional entity {entity}")
                rows["series"].append(series)
                rows["kind"].append(kind)
                rows["amount"].append(
                    Decimal(entity * 100 + month * 5).quantize(Decimal("0.01"))
                )
    schema = pa.schema(
        [
            pa.field("period", pa.string(), nullable=False),
            pa.field("entity", pa.string(), nullable=False),
            pa.field("entity_name", pa.string(), nullable=False),
            pa.field("series", pa.string(), nullable=False),
            pa.field("kind", pa.string(), nullable=False),
            pa.field("amount", pa.decimal128(12, 2), nullable=False),
        ]
    )
    source = directory / "source.parquet"
    pq.write_table(pa.Table.from_pydict(rows, schema=schema), source)
    config = init_config(source, directory / "export.json", overwrite=True)
    settings = json.loads(config.read_text(encoding="utf-8"))
    settings["columns"] = {
        "period": "code",
        "entity": "pattern",
        "entity_name": "pattern",
        "series": "code",
        "kind": "code",
        "amount": "numeric_stats",
    }
    config.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    profile_parquet(source, directory / "profile.json", config, overwrite=True)


if __name__ == "__main__":
    main()

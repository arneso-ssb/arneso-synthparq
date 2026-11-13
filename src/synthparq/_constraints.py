"""Reconcile overlapping dependencies and verify every output constraint."""

from collections import defaultdict
from typing import Any

import pyarrow as pa

from synthparq._types import _from_json
from synthparq._types import _value_type
from synthparq._types import string_to_type


def reconcile(data: dict[str, list[Any]], mappings: list[dict[str, str]]) -> None:
    # Merging equality classes is monotone: every step removes distinctions,
    # so it terminates. The existing values are used, never new code values.
    edges = [(item["from"], item["to"]) for item in mappings]
    edges += [(item["to"], item["from"]) for item in mappings if item["kind"] == "1:1"]
    changed = True
    while changed:
        changed = False
        for source, target in edges:
            parent: dict[Any, Any] = {}

            def find(value: Any, parent: dict[Any, Any] = parent) -> Any:
                root = value
                while root in parent:
                    root = parent[root]
                while value in parent:
                    following = parent[value]
                    parent[value] = root
                    value = following
                return root

            representatives: dict[Any, Any] = {}
            for a, b in zip(data[source], data[target], strict=True):
                if a in representatives:
                    first, second = find(representatives[a]), find(b)
                    if first != second:
                        parent[second] = first
                else:
                    representatives[a] = b
            if parent:
                data[target] = [find(value) for value in data[target]]
                changed = True


def verify(table: pa.Table, profile: dict[str, Any], expected_rows: int) -> None:
    if table.num_rows != expected_rows:
        raise ValueError(
            "Cannot satisfy requested row count with available unique values"
        )
    rows = table.to_pydict()
    for field in table.schema:
        if not field.nullable and table.column(field.name).null_count:
            raise ValueError("Cannot satisfy non-nullable column constraint")
    for column in profile["columns"]:
        if column["role"] == "code":
            data_type = _value_type(string_to_type(column["type"]))
            allowed = {
                _from_json(item["value"], data_type)
                for item in column["stats"]["values"]
            }
            if any(
                value is not None and value not in allowed
                for value in rows[column["name"]]
            ):
                raise ValueError(
                    "Generated values are outside approved code domains; review period roles or disable time-series handling"
                )
    key = profile.get("primary_key")
    if key:
        keys = list(zip(*(rows[name] for name in key), strict=True))
        if any(None in values for values in keys) or len(set(keys)) != table.num_rows:
            raise ValueError(
                "Cannot satisfy primary key uniqueness with these constraints"
            )
    for relation in profile.get("mappings", []):
        source, target = rows[relation["from"]], rows[relation["to"]]
        pairs = set(zip(source, target, strict=True))
        if len(pairs) != len(set(source)):
            raise ValueError("Cannot satisfy all recorded mappings simultaneously")
        if relation["kind"] == "1:1" and len(pairs) != len(set(target)):
            raise ValueError("Cannot satisfy a recorded 1:1 mapping")
    timeseries = profile.get("timeseries")
    if timeseries:
        groups: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
        for index in range(table.num_rows):
            group = tuple(rows[name][index] for name in timeseries["series_keys"])
            groups[group].append(rows[timeseries["period"]][index])
        expected = set(rows[timeseries["period"]])
        if any(
            len(periods) != len(expected) or set(periods) != expected
            for periods in groups.values()
        ):
            raise ValueError("Cannot satisfy complete, unique periods per series")

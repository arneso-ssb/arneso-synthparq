"""Readable Arrow type names and scalar JSON representations."""

import re
from datetime import date
from datetime import datetime
from decimal import Decimal
from typing import Any
from typing import cast

import pyarrow as pa

_SIMPLE_TYPES: dict[str, pa.DataType] = {
    "bool": pa.bool_(),
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "uint8": pa.uint8(),
    "uint16": pa.uint16(),
    "uint32": pa.uint32(),
    "uint64": pa.uint64(),
    "float32": pa.float32(),
    "float64": pa.float64(),
    "string": pa.string(),
    "large_string": pa.large_string(),
    "date32": pa.date32(),
    "date64": pa.date64(),
}
_SIMPLE_NAMES = {data_type: name for name, data_type in _SIMPLE_TYPES.items()}
_TIMESTAMP_RE = re.compile(r"^timestamp\[(s|ms|us|ns)(?:, tz=([^\]]+))?\]$")
_DECIMAL_RE = re.compile(r"^(decimal128|decimal256)\((\d+), (-?\d+)\)$")
_DICTIONARY_RE = re.compile(r"^dictionary<(\w+), (.+?)(, ordered)?>$")


def type_to_string(data_type: pa.DataType) -> str:
    """Convert an Arrow data type to a human-readable type string.

    Args:
        data_type: The Arrow data type.

    Returns:
        A type string that :func:`string_to_type` parses back exactly.

    Raises:
        ValueError: If the type is not supported.

    Examples:
        >>> import pyarrow as pa
        >>> type_to_string(pa.decimal128(12, 2))
        'decimal128(12, 2)'
        >>> type_to_string(pa.timestamp("us", tz="Europe/Oslo"))
        'timestamp[us, tz=Europe/Oslo]'
    """
    if pa.types.is_dictionary(data_type):
        if pa.types.is_dictionary(data_type.value_type):
            raise ValueError(f"Unsupported Arrow type: {data_type}")
        ordered = ", ordered" if data_type.ordered else ""
        index = type_to_string(data_type.index_type)
        return f"dictionary<{index}, {type_to_string(data_type.value_type)}{ordered}>"
    if pa.types.is_timestamp(data_type):
        if data_type.tz:
            return f"timestamp[{data_type.unit}, tz={data_type.tz}]"
        return f"timestamp[{data_type.unit}]"
    if pa.types.is_decimal128(data_type) or pa.types.is_decimal256(data_type):
        kind = "decimal128" if pa.types.is_decimal128(data_type) else "decimal256"
        return f"{kind}({data_type.precision}, {data_type.scale})"
    name = _SIMPLE_NAMES.get(data_type)
    if name is None:
        raise ValueError(f"Unsupported Arrow type: {data_type}")
    return name


def string_to_type(text: str) -> pa.DataType:
    """Parse a type string produced by :func:`type_to_string`.

    Args:
        text: The type string.

    Returns:
        The corresponding Arrow data type.

    Raises:
        ValueError: If the type string is not supported.

    Examples:
        >>> string_to_type("decimal128(12, 2)")
        Decimal128Type(decimal128(12, 2))
    """
    if text in _SIMPLE_TYPES:
        return _SIMPLE_TYPES[text]
    if match := _TIMESTAMP_RE.match(text):
        return pa.timestamp(cast("Any", match[1]), tz=match[2])
    if match := _DECIMAL_RE.match(text):
        factory = pa.decimal128 if match[1] == "decimal128" else pa.decimal256
        return factory(int(match[2]), int(match[3]))
    if match := _DICTIONARY_RE.match(text):
        index_type = _SIMPLE_TYPES.get(match[1])
        if index_type is None or not pa.types.is_integer(index_type):
            raise ValueError(f"Unsupported type string: {text!r}")
        value_type = string_to_type(match[2])
        if pa.types.is_dictionary(value_type):
            raise ValueError(f"Unsupported type string: {text!r}")
        return cast(
            "pa.DataType",
            pa.dictionary(cast("Any", index_type), value_type, bool(match[3])),
        )
    raise ValueError(f"Unsupported type string: {text!r}")


def _value_type(data_type: pa.DataType) -> pa.DataType:
    if pa.types.is_dictionary(data_type):
        return cast("pa.DataType", data_type.value_type)
    return data_type


def _is_numeric(data_type: pa.DataType) -> bool:
    return bool(
        pa.types.is_integer(data_type)
        or pa.types.is_floating(data_type)
        or pa.types.is_decimal(data_type)
    )


def _is_string(data_type: pa.DataType) -> bool:
    return bool(pa.types.is_string(data_type) or pa.types.is_large_string(data_type))


def _is_measure(data_type: pa.DataType) -> bool:
    unwrapped = _value_type(data_type)
    return bool(pa.types.is_floating(unwrapped) or pa.types.is_decimal(unwrapped))


def _to_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _from_json(value: Any, data_type: pa.DataType) -> Any:
    if pa.types.is_decimal(data_type):
        return Decimal(value)
    if pa.types.is_timestamp(data_type):
        return datetime.fromisoformat(value)
    if pa.types.is_date(data_type):
        return date.fromisoformat(value)
    return value

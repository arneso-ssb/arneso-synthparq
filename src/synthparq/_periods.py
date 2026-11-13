"""Recognise, format and expand supported regular calendar periods."""

import re
from datetime import date
from typing import Any

import pandas as pd
import pyarrow as pa

_PERIOD_FORMATS: dict[str, tuple[re.Pattern[str], str]] = {
    "YYYY": (re.compile(r"^(\d{4})$"), "Y"),
    "YYYYMM": (re.compile(r"^(\d{4})(\d{2})$"), "M"),
    "YYYY-MM": (re.compile(r"^(\d{4})-(\d{2})$"), "M"),
    "YYYYQn": (re.compile(r"^(\d{4})Q([1-4])$"), "Q"),
    "YYYY-Qn": (re.compile(r"^(\d{4})-Q([1-4])$"), "Q"),
    "YYYYKn": (re.compile(r"^(\d{4})K([1-4])$"), "Q"),
    "YYYY-Kn": (re.compile(r"^(\d{4})-K([1-4])$"), "Q"),
    "YYYYMMDD": (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), "D"),
    "YYYY-MM-DD": (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), "D"),
}
_NATIVE_PERIOD = "native"


def _parse_period(text: str, period_format: str) -> pd.Period | None:
    pattern, frequency = _PERIOD_FORMATS[period_format]
    match = pattern.match(text)
    if match is None:
        return None
    year = int(match[1])
    if not 1800 <= year <= 2200:
        return None
    try:
        if frequency == "Y":
            return pd.Period(year=year, freq="Y")
        if frequency == "Q":
            return pd.Period(year=year, quarter=int(match[2]), freq="Q")
        if frequency == "M":
            month = int(match[2])
            return (
                pd.Period(year=year, month=month, freq="M")
                if 1 <= month <= 12
                else None
            )
        return pd.Period(date(year, int(match[2]), int(match[3])), freq="D")
    except ValueError:
        return None


def _format_period(period: pd.Period, period_format: str) -> str:
    year = f"{period.year:04d}"
    separator = "-" if "-" in period_format else ""
    frequency = _PERIOD_FORMATS[period_format][1]
    if frequency == "Y":
        return year
    if frequency == "Q":
        letter = "K" if "K" in period_format else "Q"
        return f"{year}{separator}{letter}{period.quarter}"
    if frequency == "M":
        return f"{year}{separator}{period.month:02d}"
    return f"{year}{separator}{period.month:02d}{separator}{period.day:02d}"


def _native_period(value: Any, frequency: str) -> pd.Period:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return pd.Period(timestamp, freq=frequency)


def _period_range(timeseries: dict[str, Any], value_type: pa.DataType) -> list[Any]:
    period_format: str = timeseries["period_format"]
    frequency: str = timeseries["frequency"]
    if period_format != _NATIVE_PERIOD and period_format not in _PERIOD_FORMATS:
        raise ValueError("Unsupported period format in profile")
    if (
        period_format != _NATIVE_PERIOD
        and frequency != _PERIOD_FORMATS[period_format][1]
    ):
        raise ValueError("Period format and frequency disagree")
    if period_format == _NATIVE_PERIOD:
        start = pd.Period(timeseries["start"], freq=frequency)
        end = pd.Period(timeseries["end"], freq=frequency)
    else:
        parsed_start = _parse_period(timeseries["start"], period_format)
        parsed_end = _parse_period(timeseries["end"], period_format)
        if parsed_start is None or parsed_end is None:
            raise ValueError("Invalid period range in profile")
        start, end = parsed_start, parsed_end
    values: list[Any] = []
    for period in pd.period_range(start=start, end=end, freq=frequency):
        if period_format == _NATIVE_PERIOD:
            start_time = period.start_time.to_pydatetime()
            if pa.types.is_timestamp(value_type) and value_type.tz:
                start_time = (
                    pd.Timestamp(start_time).tz_localize(value_type.tz).to_pydatetime()
                )
            values.append(
                start_time if pa.types.is_timestamp(value_type) else start_time.date()
            )
        else:
            text = _format_period(period, period_format)
            values.append(int(text) if pa.types.is_integer(value_type) else text)
    return values

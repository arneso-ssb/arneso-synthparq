import pyarrow as pa
import pytest

from synthparq._periods import _period_range


@pytest.mark.parametrize("start,end", [("202501", "202506"), ("202503", "202507")])
def test_quarterly_month_labels_require_quarter_end_bounds(
    start: str, end: str
) -> None:
    with pytest.raises(ValueError, match="quarter-end"):
        _period_range(
            {"period_format": "YYYYMM", "frequency": "Q", "start": start, "end": end},
            pa.string(),
        )


def test_month_labels_still_reject_incompatible_frequency() -> None:
    with pytest.raises(ValueError, match="format and frequency disagree"):
        _period_range(
            {
                "period_format": "YYYYMM",
                "frequency": "Y",
                "start": "202503",
                "end": "202603",
            },
            pa.string(),
        )

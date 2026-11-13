"""Bridge generic Arrow stubs and non-generic runtime Arrow classes."""

from typing import TYPE_CHECKING
from typing import Any

import pyarrow as pa

if TYPE_CHECKING:
    Array = pa.Array[Any]
    ChunkedArray = pa.ChunkedArray[Any]
else:
    Array = pa.Array
    ChunkedArray = pa.ChunkedArray

"""Local, atomic output handling; never replace a source file."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile


def check_output(path: Path, inputs: tuple[Path, ...], overwrite: bool) -> None:
    for source in inputs:
        if path.resolve() == source.resolve() or (
            path.exists() and source.exists() and path.samefile(source)
        ):
            raise ValueError("Output must be different from every input file")
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {path}. Use --overwrite.")


@contextmanager
def atomic_output(path: Path, overwrite: bool) -> Iterator[Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=path.parent, prefix=".synthparq-", delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        yield temporary
        if overwrite:
            os.replace(temporary, path)
        else:
            # Atomic no-clobber publication, including a competing writer.
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

# Local verification

Verified on Linux on 2026-11-13, for the local development version `0.0.0`.
This is not a publication or production disclosure approval.

| Check | Result |
| --- | --- |
| Python 3.12.3 pytest (installed editable package) | 80 passed |
| Python 3.13.15 pytest (installed editable package) | 80 passed |
| Python 3.14.9 pytest (installed editable package) | 80 passed |
| Strict mypy, all three Python versions | Passed |
| Runtime typeguard, Python 3.13 | 80 passed |
| xdoctest | 2 passed |
| All template pre-commit hooks, all project files | Passed |
| Dependency declaration check (`deptry`) | Passed |
| Sphinx, fresh docs-only environment with runtime dependencies, `-W` | Passed |
| Source distribution and wheel builds | Passed |
| Isolated wheel install outside checkout; full CLI workflow with `UV_OFFLINE=1` | Passed |
| Offline installation from a wheelhouse with pinned/hash-checked runtime requirements, Python 3.12 | Passed |
| Offline CLI generation from the fabricated example | 48 rows |
| Wheel content/license inspection | Original and new MIT notices included; no datasets/profiles |
| Original `timeseriestest` working tree | Unchanged by this work |
| New repository remotes | None |

The 80 tests cover the public API/CLI, schema-only template creation, column roles,
automatic dataset-level metadata (including the deliberate period-column exception),
mapping direction and overlapping dependencies, key capacity, Decimal boundaries,
timezone preservation, deterministic generation, input validation, protected/atomic outputs,
code-domain enforcement and runtime operation without network connections.

The fixed `tests/fixtures/profile-v1.json` compatibility fixture has a different producer
version from the current tool. Compatibility is determined by profile format, not producer version.

## Repeat

```console
uv sync --locked
uv run coverage run --parallel -m pytest -o pythonpath=
uv run mypy src tests
uv run pytest --typeguard-packages=synthparq
uv run python -m xdoctest --modname=synthparq --command=all
uv run deptry .
uv run sphinx-build -E -W -b html docs docs/_build/html
uv run python scripts/verify_wheel.py
uv build
```

For a repository with no initial commit, run pre-commit with an explicit file list; once
files are tracked, use `uv run pre-commit run --all-files --hook-stage=manual`.

## Still required before release

Windows/macOS execution is configured in CI but has not been run here. Run those checks,
complete the separate publication/security/disclosure review in [the release checklist](releasing.md),
and obtain approval before creating a remote or publishing. Name availability is not reserved:
the PyPI JSON endpoint returned 404 during this work, which does not guarantee registration rights.

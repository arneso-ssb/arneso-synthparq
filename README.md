# Arneso SynthParq

Generate synthetic Parquet test datasets from reviewed, human-readable JSON profiles.
Run profiling in production, transfer only the approved profile, and generate data offline
in test. Includes a CLI (`synthparq`) and a typed Python API (`synthparq`).

**Local development version: 0.0.0. Not published. First beta target: 0.1.0.**

## Install

Requires Python 3.12–3.14. From this checkout:

```console
uv tool install .
synthparq --help
```

Or use `pipx install .`. Once a release has been separately approved and published,
installation will be `uv tool install arneso-synthparq==0.1.0`.
See the [operator guide](docs/user-guide.md) for wheel-based and offline installation.

## Quickstart

In production:

```console
synthparq profile data.parquet --init-config export.json
```

Edit `export.json` **before** profiling. Every column starts as `schema_only`.
Use `pattern` for fake IDs/names, `code` only for approved public values, and
`numeric_stats` for approved numeric summaries.

```console
synthparq profile data.parquet --config export.json --out profile.json
```

Review `profile.json` for disclosure risk, then transfer **only that file** to test:

```console
synthparq generate profile.json --out synthetic.parquet --seed 42
```

Use `--rows 1000` to request a different size. Complete time series round the row count
up; the CLI prints the actual count. Outputs are protected unless `--overwrite` is given.

## Important privacy boundary

This is **not an automatic anonymisation tool**. You decide what may be exported and
must review the resulting profile under your organisation's disclosure rules.

- Column roles govern per-column values and statistics.
- **Profiling always exports a rounded row count and detected keys/mappings.**
- With `timeseries: "auto"` (the default), detected period ranges and frequency are exported,
  **even if the period column is `schema_only`**. Use `"none"` to disable this.
- Column names and relationships can themselves be sensitive.
- Rounding and minimum-frequency suppression are safeguards, not privacy proofs.
- Synthetic data can coincidentally match real values. Do not treat it as certified anonymous.

No original filename, arbitrary Arrow/pandas metadata, encoded schema blob, raw relationship
tuples, telemetry, or network lookup is included by the tool. Runtime commands use local files.

## Documentation and examples

- [Operator guide](docs/user-guide.md): production-to-test steps, settings, troubleshooting.
- [Profile format and compatibility](docs/profile-format.md).
- [Release checklist](docs/releasing.md).
- [Local verification results](docs/verification.md).
- [Fabricated example](examples/README.md): reproducible source, config and profile with no
  production-derived data.

<!-- github-only -->

## Develop

```console
uv sync --locked
uv run pytest -o pythonpath=
uv run mypy src tests
uv run pytest --typeguard-packages=synthparq
uv run python -m xdoctest synthparq all
uv run sphinx-build -W -b html docs docs/_build/html
```

Run `uv run pre-commit run --files ...` on changed files (hooks can modify them).
The repository is based on Statistics Norway's Cruft template at `2026.11.11`;
`.cruft.json` preserves the template pin and all generation answers.

## License and provenance

MIT; copyright 2026 Statistics Norway. The initial implementation was extracted from
Arne Sørli's MIT-licensed `timeseriestest` project and hardened here. No production-derived
Parquet files or profiles from that repository are included.

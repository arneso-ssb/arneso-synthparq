# Arneso SynthParq

Generate synthetic Parquet datasets from a reviewed, human-readable profile.
Run profiling in production, transfer only the approved JSON profile, then generate
synthetic data offline in test.

The Python distribution is `arneso-synthparq`; the command and import package are `synthparq`.
The project is currently local and unpublished, with `0.1.0` as the first beta target.

**This is not automatic anonymisation.** Classify columns before profiling and review
every profile before transfer. Dataset-level metadata is exported even when all column
roles are `schema_only`; automatic time-series metadata can include period start/end values.

Start with the [operator guide](user-guide.md), then consult the [CLI/API reference](reference.md).

```{toctree}
:maxdepth: 1

user-guide
reference
profile-format
releasing
verification
contributing
codeofconduct
license
```

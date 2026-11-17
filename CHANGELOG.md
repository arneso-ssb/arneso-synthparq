# Changelog

## Unreleased — target 0.1.0 beta

- Rename the `code` column role to `category` and `force_code` to `force_category`.
  This is a breaking prototype revision with no aliases; profile format remains 1.
- Add a domain glossary and complete JSON field reference with independent/AI
  generation rules, disclosure boundaries and frequency-suppression examples.
- Standalone `synthparq` CLI and public Python API extracted from `timeseriestest`.
- Human-readable Parquet profiles with column roles and automatic dataset-level metadata.
- Local-only runtime, protected/atomic outputs and input validation.
- Verified candidate keys and all recorded pairwise mappings, including overlaps.
- Decimal boundary handling, reproducibility and format-version compatibility tests.
- Operator/offline installation guide and wholly fabricated example artifacts.
- Detect quarterly cadence in quarter-end `YYYYMM`/`YYYY-MM` values and preserve
  their month labels during generation instead of inventing intervening months.

Initial template version remains 0.0.0; no package has been published.

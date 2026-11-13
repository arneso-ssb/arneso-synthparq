# Operator guide

## What goes where

1. **Production:** inspect the schema, classify columns in a config, and profile the file.
2. **Production:** review and approve the profile for disclosure.
3. **Transfer:** move only the approved JSON profile through an approved channel.
4. **Test:** generate synthetic Parquet from that profile, with no access to the source file.

Install the tool in both environments. They need not run the same tool version if both
support the profile format. For reproducible table contents, use the same profile, seed,
tool version and dependency versions. Cross-version results and byte-identical Parquet
files are not promised.

## Installation

Python 3.12–3.14 is required. The initial project is local and unpublished:

```console
uv tool install /path/to/arneso-synthparq
```

Alternatively, `pipx install /path/to/arneso-synthparq`. From a development checkout,
use `uv sync --locked`, then prefix commands with `uv run`.

After a separately approved release to PyPI, the intended install command is
`uv tool install arneso-synthparq==0.1.0` (or `pipx install arneso-synthparq==0.1.0`).
Do not assume that version is already published.

### Offline installation

Do not access PyPI directly from production unless your organisation permits it. Prepare
an approved wheel bundle on a connected machine **matching the target OS, architecture
and Python version**. In the checkout:

```console
uv build
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements-runtime.txt
python -m pip download --only-binary=:all: --require-hashes -r requirements-runtime.txt --dest wheelhouse
```

Copy the locally built project wheel from `dist/` into `wheelhouse/`. Verify licenses,
security checks and hashes under your organisation's process. Transfer the approved
wheelhouse and requirements file to the target, then install into an isolated environment:

```console
python -m venv .venv
.venv/bin/python -m pip install --no-index --find-links wheelhouse --require-hashes -r requirements-runtime.txt
.venv/bin/python -m pip install --no-index --no-deps wheelhouse/arneso_synthparq-0.0.0-py3-none-any.whl
.venv/bin/synthparq --help
```

Windows PowerShell uses these executable paths instead:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse --require-hashes -r requirements-runtime.txt
.\.venv\Scripts\python.exe -m pip install --no-index --no-deps wheelhouse\arneso_synthparq-0.0.0-py3-none-any.whl
.\.venv\Scripts\synthparq.exe --help
```

Use a project-wheel filename matching the actual approved version. Review its hash too;
the exported dependency hashes do not authenticate the locally built project wheel.
No build tools or runtime internet access are required when installing the complete wheel bundle.

## 1. Create a config template in production

```console
synthparq profile data.parquet --init-config export.json
```

This reads the Parquet schema, **not data rows**. Every column starts as `schema_only`.
It does not copy arbitrary schema metadata. Unsupported types cause a clear error.

## 2. Classify columns before profiling

Someone with domain knowledge must edit `export.json`:

| Role | Exported per-column information | Generation |
| --- | --- | --- |
| `schema_only` | Name, type and nullability only | Type-based placeholders |
| `pattern` | Null share, length range, character classes, rounded distinct count | Fake strings; not original names/IDs |
| `code` | Null share, approved values occurring at least `k` times, rounded counts and suppressed share | Samples only the approved values |
| `numeric_stats` | Null share; rounded min/max, mean/std, distinct count and coarse histogram | Samples the histogram; supports Decimal |

Example excerpt (keep the surrounding settings written by `--init-config`):

```json
"columns": {
  "period": "code",
  "entity": "pattern",
  "entity_name": "pattern",
  "series": "code",
  "amount": "numeric_stats"
}
```

Never mark private names or identifiers as `code` just to make the synthetic data look
realistic. A format pattern can itself be disclosive; leave the role `schema_only` if unsure.

### Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `k` | `5` | Export a code only if it occurs at least this often. Merge numeric bins with fewer rows; suppress numeric summaries if fewer than `k` finite observations exist. |
| `significant_digits` | `3` | Round counts and statistics: 18,078 becomes 18,100; 0.012345 becomes 0.0123. Not decimal places. Valid range: 1–15. |
| `max_key_size` | `5` | Search candidate keys of 1–5 columns. Smaller limits are faster. |
| `mapping_max_distinct` | `10000` | Skip relationship detection for columns above this distinct-count limit. |
| `timeseries` | `"auto"` | Detect and export period metadata. Use `"none"` to disable, or an explicit role object below. |
| `force_code` | `[]` | Bypass the identifier-like check only for named, reviewed `code` columns. Does not bypass `k`. |

A `code` column is identifier-like when more than half of its non-null observations
are distinct. Unknown config settings, invalid ranges, or unknown columns fail before
reading data rows. Missing columns default to `schema_only` with a warning.

## 3. Profile in production

```console
synthparq profile data.parquet --config export.json --out profile.json
```

**Even without a config, this exports dataset-level information:** rounded row count,
candidate primary key, column relationships, and automatically detected time-series
metadata. `schema_only` does not suppress these disclosures. There are no separate
dataset-level permission switches.

Detected candidate keys contain no nulls and identify each row in this source file;
they are not proof of a business key. Float/Decimal measurements are excluded from key
and mapping detection. Pairwise mappings describe the source snapshot, not future data.

Mappings use `from` as the determinant:

```json
{"from": "entity", "to": "entity_name", "kind": "1:1"}
```

`N:1` means each `from` value has one `to` value, while multiple `from` values may share
it. The inverse `1:N` relationship is represented by reversing the endpoints, not by
a separate `1:N` label. `N:N` relationships are not stored. Generation preserves these
functional dependencies, but a small sample can contain fewer categories than the source.

## 4. Review and approve before transfer

Check **all** profile fields, not just code lists:

- Column names/types and relationships are approved to disclose.
- No real private names or identifiers were mistakenly authorised as codes.
- Numeric extrema and summary values do not expose outliers or individual units.
- Pattern lengths, null shares, distinct counts and the row count are acceptable.
- Period start/end, frequency and series count are acceptable.
- Candidate keys and time-series roles are plausible.

Rounding and `k` suppression are not differential privacy or a formal anonymity guarantee.
If the profile is unsafe, change the config and rerun profiling. Use `--overwrite` only
when deliberately replacing the previous output. Never transfer an unreviewed profile.
Where dataset-level disclosures are unacceptable, **do not transfer the profile**;
this release does not provide fine-grained switches for all those fields.

## 5. Transfer the approved text

Transfer only `profile.json` using your organisation's approved process. Neither the source
Parquet nor the config is required for generation. The config may be retained privately
as an audit record. Do not publish production-derived example profiles or datasets without
separate disclosure approval.

## 6. Generate in test

```console
synthparq generate profile.json --out synthetic.parquet --seed 42
synthparq generate profile.json --out larger.parquet --seed 42 --rows 1000
```

These commands also work in PowerShell; quote paths containing spaces. In an unactivated
Windows virtual environment, replace `synthparq` with `.\.venv\Scripts\synthparq.exe`.

The default size is the rounded profile row count. The CLI reports the actual output count.
Generation fails rather than silently returning too few rows or breaking a key/mapping.
You may need fewer rows, a different reviewed config, or corrected structural assumptions.
No output is published if generation fails. Existing files require `--overwrite`.

## Time series

Detection recognises long-format tables whose candidate key includes a period column
and which have numeric measurements. Supported text/integer periods include `2025`,
`202501`, `2025-01`, `2025Q1`, `2025-Q1`, `2025K1`, `2025-K1`, `20250131`, `2025-01-31`
(years 1800–2200). Dates and midnight timestamps are also recognised; subdaily
timestamps are not converted into daily series.

For explicit roles:

```json
"timeseries": {
  "period": "period",
  "series_keys": ["entity", "series"],
  "values": ["amount"]
}
```

The period column does not need the `code` role. Detection exports its start/end and
frequency independently of that role. Every generated series spans the complete regular
range. Requested rows round up to a multiple of the number of periods. A dataset without
series keys can contain only one series.

If the period column is `code`, every generated period must also be in its approved code
list. Gaps or suppressed periods can therefore cause a clear error instead of silently
inventing codes. Review the period role (often `schema_only` is sufficient for time-series
generation) or disable time-series handling.

Each measurement starts with a histogram sample, then follows a multiplicative random
walk with 5% standard deviation per step, clipped to the exported bounds. **5% is not a
hard bound.** Zero stays zero. There is no learned trend, seasonality or shared movement
between series. With no exported numeric histogram the generator uses placeholder levels.

## Python API

```python
from pathlib import Path
from synthparq import init_config, profile_parquet, generate_parquet

# Production: run separately, editing export.json before profiling.
init_config(Path("data.parquet"), Path("export.json"))
profile_parquet(Path("data.parquet"), Path("profile.json"), Path("export.json"))

# Test: only profile.json is needed.
generate_parquet(Path("profile.json"), Path("synthetic.parquet"), seed=42)
```

All three accept keyword-only `overwrite=True`. Inputs cannot be used as their own outputs,
even with overwrite enabled.

## Troubleshooting and limitations

| Symptom | Action |
| --- | --- |
| Output already exists | Choose another path or intentionally use `--overwrite`. |
| Config column is unknown | Check spelling and schema drift. |
| Identifier-like code column | Prefer `pattern`; use `force_code` only after review. |
| Code column has no approved values | All codes were suppressed. Review its role or `k`; values will not be invented. |
| Insufficient unique key capacity | Request fewer rows or review the permitted key domains. |
| Cannot satisfy mappings/keys | Review overlapping constraints and roles. The generator is conservative, not a general constraint solver. |
| Unsupported format/features | Use a tool version that supports this profile. Producer versions need not match. |
| Unsupported Arrow type | Nested/binary types are out of scope. See the format reference. |

The generator verifies all recorded mappings, including overlaps. Reconciliation may reduce
category diversity and introduce extra relationships, so marginal distributions are approximate.
Some feasible combinations of constraints may still be rejected by the conservative generator.
It is not a general relational model or a faithful statistical simulation.

Profiling and generation hold data in memory. Candidate-key search is combinatorial; use a
smaller `max_key_size` on wide tables. There is no claim of large-scale streaming support.

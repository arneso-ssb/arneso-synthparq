# Profile format and compatibility

Profiles are UTF-8 JSON objects, format version **1**. They contain no encoded Arrow schema
or arbitrary source metadata. Unsupported types fail instead of being guessed.

For every field in both configuration and profile files, nested statistics, scalar
encodings and independent/AI generation rules, read the [JSON reference](json-reference.md).

**Prototype rename:** the role is now `category` and the configuration setting is
`force_category`. The former names `code` and `force_code` are rejected, without
changing `format_version: 1`. Regenerate older files or edit these tokens explicitly;
this prototype revision does not provide compatibility aliases.

| Field | Meaning |
| --- | --- |
| `format_version` | Version of the profile contract, independent of tool version |
| `producer` | Tool distribution name and version; informational, not a compatibility gate |
| `row_count` | Rounded source row count |
| `export_settings` | Minimum frequency `k` and significant-digit rounding |
| `columns` | Ordered name/type/nullability/role records, with role-specific `stats` |
| `primary_key` | Candidate key column names or `null` |
| `mappings` | Pairwise `{from, to, kind}` dependencies (`1:1` or `N:1`) |
| `timeseries` | Period column/format/frequency/start/end, series keys, values and rounded series count, or `null` |

`required_features`, if present, must currently be an empty list. Unknown required features
and unsupported format versions are rejected with an actionable error. Compatible producer
versions may differ between production and test. Fixture tests cover profiles from earlier
prototype/tool versions; keep those fixtures when changing the implementation.

For `timeseries`, `period_format` describes the labels, while `frequency` describes
the cadence. `YYYYMM` and `YYYY-MM` support both monthly (`M`) and quarterly (`Q`)
frequency. Quarterly month labels use quarter-end months, preserving their string
or integer representation. Older readers may reject this format/frequency combination;
use an updated SynthParq on both sides. Existing profiles are not re-inferred during
generation: regenerate them to detect quarterly month labels.

## Type strings

Supported scalar types:

- `bool`, `int8`, `int16`, `int32`, `int64`, corresponding `uint` types.
- `float32`, `float64`, `string`, `large_string`, `date32`, `date64`.
- `timestamp[s]`, `timestamp[ms]`, `timestamp[us]`, `timestamp[ns]`, optionally with
  `, tz=Europe/Oslo` (or another Arrow-supported timezone).
- `decimal128(12, 2)` and `decimal256(60, 10)`; Parquet requires scale between zero and precision.
- `dictionary<int8, string>` and `dictionary<int16, string, ordered>`; values may be any
  supported non-dictionary scalar and indices must use a supported integer type.

The generated table preserves the source's logical schema as read from Parquet, not its
compression, row groups or physical encodings. Arrow/pandas metadata is deliberately omitted.
Numeric summaries/sampling use floating-point approximations even for Decimal; Decimal output
is quantised and bounded using its declared precision/scale. Original exact Decimal values
are not reconstructed.

## Evolution policy

- Use semantic versioning for the tool; document changes in `CHANGELOG.md`.
- Preserve supported version-1 readers across compatible releases; the explicit
  prototype rename above is a breaking pre-release revision, not a compatible release.
- Introduce a new profile version or explicit required feature for incompatible semantics.
- Do not infer compatibility by comparing producer-version strings.
- Reproducibility requires the same tool/dependency environment, not just the same format version.

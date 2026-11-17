# SynthParq

SynthParq describes approved properties of a source dataset so that synthetic test
data can be created without transferring its original records.

## Language

**Export configuration**:
The operator's choices about which column properties may be disclosed and which
profiling safeguards apply.
_Avoid_: Profile, generation specification

**Profile**:
A reviewable description of a dataset's schema, authorised column properties and
observed structural relationships, used as the input for synthetic generation.
_Avoid_: Original data, anonymised dataset

**Column role**:
A disclosure choice describing which properties of a column may be profiled, not
its analytical purpose or a certification that its contents are safe.

**Category role**:
Permission to export observed category values authorised for disclosure, subject to
frequency suppression, together with rounded counts; generation uses only that exported set.
_Avoid_: Code role, Klass role

**Approved category set**:
The category values retained in a reviewed profile, which may omit unobserved or
suppressed members of a wider classification.
_Avoid_: Complete classification, Klass code list

**Frequency suppression**:
Omission of a category value whose source-row count is below the chosen minimum
frequency, or of numeric information with insufficient supporting observations.

**Pattern role**:
Permission to disclose aggregate string lengths, character classes and diversity,
rather than the strings themselves.

**Numeric statistics role**:
Permission to disclose aggregate numeric summaries and a histogram rather than
individual numeric observations.

**Schema-only role**:
A choice to disclose no per-column values or statistics; dataset-level metadata
remains a separate disclosure consideration.

**Series key**:
An attribute, or combination of attributes, identifying one time series whose
observations are indexed by a period.

**Period label**:
The representation of a period, distinct from its cadence: a year-month label can
represent a monthly observation or the end month of a quarterly observation.

**Synthetic data**:
Artificial records consistent with selected properties of a reviewed profile,
not reconstructed original records or certified anonymous data.

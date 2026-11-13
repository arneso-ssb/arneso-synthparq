# Local delivery and release checklist

## Current state

The project is local, with no configured remote or published release. Template version
`0.0.0` is retained; the first usable beta target is `0.1.0`.

The template's release workflow is manual-only and gated by repository variable
`SYNTHPARQ_PUBLISH_ENABLED=true`. Do not enable it, configure publishing credentials,
create a remote or publish without separate approval. The existing project `timeseriestest`
must not be changed to depend on this package as part of this delivery.

## Before an approved beta release

- Recheck availability of distribution name `arneso-synthparq`; a PyPI lookup returning 404
  is not a reservation or proof that the name can be registered.
- Review disclosure boundaries and operator documentation with a domain expert.
- Verify all unit/API/CLI tests, strict mypy, runtime typeguard, doctests and pre-commit checks.
- Build documentation with warnings treated as errors.
- Build a wheel and install it into a fresh environment outside the source checkout.
- Test the fabricated example end to end, including offline installation/generation.
- Run CI on Python 3.12–3.14 and Linux/Windows/macOS; local Linux results alone do not
  certify the other platforms.
- Keep compatibility fixtures and verify producer versions can differ.
- Review the wheel/sdist contents: no production-derived source, profiles, datasets or secrets.
- Review dependencies/licenses and test the approved offline wheel bundle for each target.
- Set version `0.1.0`, update lockfile/changelog, and rerun checks before building release artifacts.
- After separate approval, create/configure GitHub and PyPI, trusted publishing and protected
  release environments. Ensure publication depends on successful checks and human approval
  before enabling the inherited publishing workflow.

## Template provenance

Created with Cruft from
`https://github.com/statisticsnorway/ssb-pypitemplate.git --checkout=2026.11.11`.
All 14 supplied answers are recorded in `.cruft.json` and `.cookiecutter.json`.
Use `cruft check` / `cruft update` for future template maintenance, reviewing the changes.

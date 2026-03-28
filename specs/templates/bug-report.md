# Bug Report Template

Copy this file to `bugs/BUG-NNN-short-slug.md` and fill in all sections.
Replace `NNN` with the next sequential number (check `bugs/` for the current highest).

---

# BUG-NNN: One-line summary

**Status:** open | in_progress | fixed | wont_fix
**Severity:** critical | high | medium | low
**Product area:** frontend | backend | auth | data | infra
**Date filed:** YYYY-MM-DD
**Filed by:** user | automated

---

## Description

What is broken? One paragraph, plain language.

## Steps to reproduce

1. Step one
2. Step two
3. Step three

## Expected behaviour

What should happen.

## Actual behaviour

What actually happens. Include error messages verbatim, console output, or screenshots if relevant.

## Environment

- **URL:** e.g. `https://your-app.example.com/`
- **Screen / flow:** e.g. Detail panel, edit mode
- **Auth state:** signed in | guest | signed out
- **Browser:** e.g. Safari 18, Chrome 131
- **Device:** e.g. MacBook Pro, iPhone 15

## Affected spec

Link to the product spec AC or user story this should have covered, if known.
Leave blank if this is a gap not covered by any existing AC.

- Spec file: `specs/products/[file].md`
- Section / AC: e.g. "AC-3: User can edit brew fields inline"

---

## Resolution
*Fill in when fixing.*

### Root cause

What caused this? Be specific — component, function, line if known.

### Fix summary

What was changed and why. Include PR or commit reference.

- PR / commit: `fix(scope): description` — #PR or SHA

### Regression test added

A bug fix is not complete without a test that would have caught it.

- **Added:** yes | no (if no, explain why)
- **Test file:** e.g. `tests/test_brews.py` or `e2e/brew-detail.spec.ts`
- **Test name:** e.g. `test_brew_edit_saves_correctly`

### Spec / AC updated

If this bug revealed a gap in the product spec, update it.

- **Updated:** yes | no | not applicable
- **File + section:** e.g. `specs/products/[product-spec].md` § "[section name]"
- **Change:** brief description of what was added or corrected

### Architectural implication

Did this bug reveal a design decision, a missing constraint, or a pattern we should standardise?
If yes, record it — either amend an existing ADR or create a new one.

- **ADR impact:** none | amended ADR-NNN | new ADR created (ADR-NNN)
- **Summary:** one sentence on what the architectural lesson is

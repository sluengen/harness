# Design: [Feature Name]

**Feature:** [manifest task id]
**Author:** architect
**Created:** [date]
**Input:** [path to product spec]
**Baseline:** [path to previous design if applicable]
**Status:** Ready for Dev

---

## Overview

One paragraph describing the scope of this design. What is being built or changed, and why. Reference the product spec and any carry-forward context from previous versions. Flag any significant breaking changes upfront.

---

## 1. Changes Required

The bulk of the design. Break this into numbered subsections — one per logical area of change. Each subsection should be specific enough that the developer can implement from it without guessing.

### 1.1 [Area of change]

Describe the change. Include:
- Before/after comparisons where applicable
- Exact field names, types, constraints
- Schema snippets for data model changes
- SQL DDL for database changes
- Function signatures for code changes

### 1.2 [Area of change]

...

---

## 2. Data Models

### 2.1 Validation Models

Define or update validation models. Show the complete model, not just the delta — the dev should not need to diff against the previous version.

```python
class ExampleModel(BaseModel):
    field: type
```

### 2.2 Database Schema

Define CREATE TABLE statements or ALTER TABLE migrations if the database schema changes. If unchanged, state that explicitly.

```sql
CREATE TABLE example (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ...
);
```

---

## 3. API / Interface Design

Document every endpoint or interface affected by this design:

- Route / method signature
- Request/response schemas
- Status codes
- Auth requirements
- Error responses

---

## 4. Architecture Decision Records

Document significant design trade-offs. Skip if no meaningful trade-offs exist.

### ADR-1: [Decision title]

**Context**: Why this decision needed to be made.
**Options considered**: List the alternatives.
**Decision**: What was chosen.
**Rationale**: Why.
**Consequences**: What this means for future changes.

---

## 5. File Manifest

Complete list of every file the dev must create or modify.

| File | Operation | Notes |
|------|-----------|-------|
| | Create / Modify | |

---

## 6. Test Strategy

Enumerate the test cases the dev must write before implementing. Group by acceptance criterion. Every AC must have at least one test case.

### AC-N: [AC description]

| Test | Input | Expected |
|------|-------|----------|
| Valid case | `{field: value}` | passes validation |
| Invalid case | `{field: bad_value}` | fails with error |
| Edge case | `{field: boundary_value}` | passes / fails |

---

## 7. Security Considerations

Address each trust boundary relevant to this design:

- **Input validation**: What user inputs are validated, and how
- **File I/O**: Any new file read/write operations and how they're made safe
- **Database**: Any new queries — confirm parameterized, no string interpolation of user data
- **Error messages**: Confirm error messages don't expose internal paths or stack traces
- **Data integrity**: Any new constraints that protect data consistency

---

## 8. TDD Implementation Order

Prescribe the sequence the dev should follow. Tests must be written before implementation code for each step.

1. Write failing tests for [AC group]
2. Implement [change] to make tests pass
3. Write failing tests for [AC group]
4. Implement [change] to make tests pass
5. Run full test suite — confirm all pass
6. Run linter — fix any errors

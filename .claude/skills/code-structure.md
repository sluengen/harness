# Code Structure

Structural guidance for writing maintainable, modular code. Both dev agents follow these rules when building; the reviewer enforces them during review.

## Size Limits

Soft limits trigger a "should I split this?" check. Hard limits are a reviewer FAIL unless justified in a code comment explaining why the file must stay unified.

### Frontend (React/TypeScript)

| Unit | Soft limit | Hard limit |
|------|-----------|------------|
| Component file | 300 lines | 500 lines |
| Custom hook | 200 lines | 300 lines |
| Utility/lib module | 300 lines | 500 lines |
| Single function/handler | 40 lines | 60 lines |

### Backend (Python)

| Unit | Soft limit | Hard limit |
|------|-----------|------------|
| Module (service, router, etc.) | 400 lines | 600 lines |
| Single function | 40 lines | 60 lines |
| Schema file (Pydantic models) | 400 lines | 600 lines |

Schema and type definition files get the higher limit because they're declarative — field lists are long but not complex.

## When to Split

### Components (Frontend)

Split a component when any of these are true:
- It manages more than **10 useState/useReducer calls** — extract a custom hook
- It renders more than **3 distinct visual sections** — extract sub-components
- The same form section appears in **2+ screens** — extract a shared component
- The file exceeds the soft limit and has identifiable sub-concerns

**Segment pattern (reference):** For overlay/panel UIs with multiple editable sections, each segment should have:
- A view sub-component (read-only display)
- An edit sub-component (form inputs + draft state)
- A parent segment that switches between them

Screens should compose segments, not inline entire forms.

### Hooks (Frontend)

Split a hook when:
- It manages **more than one concern** (e.g., fetch + form state + validation)
- It has **more than 5 state variables** for a single concern — the concern itself may need decomposition
- The same state management pattern repeats across hooks — extract a shared primitive

### Repeated Patterns (Frontend and Backend)

**Three-strike rule:** if a pattern appears 3+ times, extract it.

- **Numeric input parsing** (onChange/onBlur/onKeyDown with parseFloat) — extract a `useNumericInput` hook
- **CRUD service functions** with identical signatures — use a factory or generic
- **API call + loading + error state** — use a shared `useApi` or `useFetch` pattern
- **Button groups / selector patterns** — extract a shared component

When extracting, the shared abstraction lives in:
- Frontend: `components/ui/` (visual), `hooks/` (behaviour), `lib/` (pure logic)
- Backend: `app/utils/` (helpers), existing service/repository if domain-specific

### Modules (Backend)

Split a module when:
- A service contains logic for **2+ unrelated domains** — one service per domain
- A router file defines **more than 10 endpoints** — split by sub-resource
- A module exceeds the soft limit and has identifiable sub-concerns

Standard backend layering — maintain it:
```
routers (HTTP) → services (business logic) → repositories (DB queries) → models (ORM)
```

No business logic in routers. No HTTP concepts in services. No queries scattered outside repositories.

## Composition Over Inline

### Frontend screens

Screens are **composers**, not implementors. A screen should:
1. Fetch data (or delegate to a hook)
2. Manage top-level state transitions (edit mode, loading, error)
3. Compose sub-components for each visual section
4. Handle navigation

A screen should NOT:
- Define form field parsing logic inline
- Contain 50+ useState calls for individual form fields
- Render 500+ lines of JSX in a single return statement
- Duplicate form sections that exist in other screens

### Form state management

When a form has more than 10 fields:
- Group related fields into a single state object (e.g., `recipeDraft: { dose, water, grind, temp }`)
- Use a reducer or custom hook for the group — not individual useState per field
- Field-level parsing/validation lives in the hook, not in JSX callbacks

### Backend services

Services are **domain functions**, not god objects:
- One service file per domain
- Services call repositories for data access, not raw ORM queries
- Services can call other services horizontally
- No service should depend on router-layer concepts (Request, Response, status codes)

## What the Reviewer Checks

The reviewer adds these checks to Stage 2:

1. **File size** — any file exceeding the hard limit without justification is a High finding
2. **File size (soft)** — any file exceeding the soft limit gets a Medium finding suggesting where to split
3. **Repeated patterns** — same logic in 3+ places is a Medium finding with extraction suggestion
4. **Concern mixing** — business logic in a router, HTTP concepts in a service, form parsing inline in JSX is a High finding
5. **God components** — a component with 15+ useState calls is a High finding
6. **Duplicated form sections** — same form fields rendered in 2+ places is a Medium finding

## Existing Code

These rules apply to **new code and modified files**. Pre-existing violations in untouched files are not review findings — they're refactor candidates tracked separately. But: if a task touches a file that's already over the limit, the reviewer should flag it as "this file is already over the soft limit — consider splitting as part of this task if the change makes it worse."

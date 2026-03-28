# Architecture Principles

**Status:** Active

These principles govern technical and system design decisions. They are distinct from the product principles in `strategy/principles.md` — those define what we build and why; these define how we build it. All architecture decisions (recorded in `specs/decisions/`) should be traceable to one or more of these principles.

---

## Data

**User data portability is a hard constraint, not a feature.**
A user must always be able to export all of their data in a standard, open format and take it elsewhere. This is not something we add later — it is a precondition for trust. No internal architecture decision should make full data export impractical. If a design makes portability hard, change the design.

**Aggregation requires explicit opt-in consent — never implicit.**
If the product's value proposition depends on aggregate data, that aggregation must be gated by explicit, revocable consent at every level. Default is no sharing. Design the consent model before designing the aggregation pipeline. Any system that could expose individual user data in aggregate outputs needs an audit trail and a documented privacy boundary.

---

## API and Backend

**The backend API is the strategic asset — own it from day one.**
The backend is where the domain logic, data model, and core pipeline live. The frontend is replaceable; the backend is not. Never let convenience push domain logic into the frontend, a third-party service, or a database trigger. If it's core to the product, it lives in the API.

**Validate at every system boundary.**
All inputs are untrusted until validated by the API layer. This includes: incoming HTTP requests, imported files, data from third-party integrations, and anything that crosses a process boundary. Validate schema and type at the edge; don't assume internal services are safe.

**API contracts are stable; implementations are replaceable.**
Version the API from day one. Breaking changes to the public API require a new version. Internal implementation details (database schema, service structure) can change freely as long as the contract holds.

---

## Frontend

**The frontend is a view layer — domain logic does not live there.**
Business rules, validation, access control, and data transformation belong in the API. The frontend renders state and captures input.

---

## Infrastructure

**PaaS over self-managed infrastructure.**
Infrastructure is a cost and a distraction, not a differentiator. Use a managed PaaS for hosting, managed databases, and compute. Never provision bare metal, manage Kubernetes clusters, or own a database server unless there is a specific, documented reason that commodity infrastructure cannot meet the requirement.

**No platform lock-in in application code.**
We use PaaS for deployment, not for application architecture. Application code should be portable — no proprietary SDKs in the business logic layer, no vendor-specific database extensions in the core data model. Configuration, environment variables, and deployment manifests can be platform-specific; the application itself cannot.

---

## Operations

**Every system must be solo-operable.**
If understanding, deploying, or debugging a component requires more than one person's knowledge, it's too complex for this stage. Complexity that requires a team to maintain is a liability.

**Every service dependency is a future obligation.**
Each third-party service we integrate is something we'll eventually debug, upgrade, migrate from, or pay for at an inconvenient time. Before adding a service dependency, ask: is this truly a commodity concern we shouldn't own? Is the vendor stable? Can we replace it in a week if needed? Prefer services with clean, standard APIs over proprietary SDKs.

---

## Security

**Authentication and authorisation are never bolted on.**
Design auth into the data model and API from the first line of code. Every endpoint has an explicit authorisation model: who can call it, under what conditions, and what happens if they can't. Multi-tenancy means one user's data is never accessible to another — enforce this at the query level, not at the application level.

**Security defaults to most restrictive.**
New features start locked down and open up. Never ship a feature with "we'll add auth later" — later doesn't come. API endpoints default to requiring authentication. Data fields default to private. Sharing and aggregation default to off.

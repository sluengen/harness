# ADR 0002 — The in-container review engine is Claude; `--engine codex` is a host-only option

- **Status:** Accepted
- **Date:** 2026-07-02 (CAL-925)
- **Source:** CAL-925 (this decision); relates to CAL-866 (the original bwrap finding) and ADR [0001](0001-cloud-runnable-harness-loop.md) (which already recorded the same constraint for the cloud loop).

## Context

`harness review --engine codex` is meant to give a **cross-model** second opinion — a Codex reviewer over a Claude-authored diff (the generator/evaluator split). Inside the `harness:dev` container that engine does not work:

- The image installs the Codex CLI via npm (`docker/Dockerfile`) but no `bubblewrap` apt package, so Codex falls back to its **bundled `bwrap`**.
- The container runs **unprivileged**, so that `bwrap` cannot create a new user namespace (`CLONE_NEWUSER` is blocked). Codex's `--sandbox read-only` mode wraps every command it runs in `bwrap`, so a real review **fails per-command and produces no usable verdict** (CAL-866).
- A trivial Codex prompt that sandboxes no command still *succeeds*, which is misleading — it looks like the engine works until a review actually shells out.

So Codex is **not a usable in-container review engine today**, and the `--engine codex` value silently degrades there.

Two ways forward were weighed:

- **(a) Make the sandbox work in-container** — install/allow `bubblewrap` and grant the container the user-namespace + seccomp privileges its `bwrap` needs (e.g. `CAP_SYS_ADMIN`, `--privileged`, or a custom seccomp profile), or run Codex under a different working sandbox mode.
- **(b) Accept Claude-only reviews in-container** — formally document the in-container review engine as Claude, and treat `--engine codex` as a **host-only / cross-model** option.

## Decision

**Option (b): the in-container review engine is Claude. `--engine codex` is a host-only / cross-model option.**

- Inside the container (`~/bin/harness review`, and the `/harness run` verb loop), the review engine is **Claude** — available on the standard tier, auto-compacting, and already the `--engine` default (CAL-701).
- **`--engine codex` is supported host-side**, where Codex's `bwrap` can create the user namespace its read-only sandbox needs and `~/.codex` subscription auth is present. It remains the way to get a genuine cross-model review.
- The container gains **no new privileges**. `docker/Dockerfile` is unchanged by this decision.

This is recorded in `commands/harness.md`, `agents/reviewer.md`, and `specs/features/verb-model.md` so the contract is visible where an operator or an orchestrating agent reads about the review engine.

### Why (b), not (a)

- **The container reviews untrusted diffs.** The diff under review and the ticket description are untrusted prompt content (that is *why* both engines run read-only). Granting that container a new user namespace + a looser **seccomp** profile / `CAP_SYS_ADMIN` — the **privilege** loosening `bwrap` needs — is a real, standing security regression against a workload whose entire threat model is "a prompt-injection in the diff must not be able to mutate the host." Paying that cost for a *second* review engine is a bad trade.
- **The gate stays available without it.** Claude reviewing a Claude-authored diff gives up the model-*family* diversity Codex brings, but it keeps the gate *available* — a depleted Codex tier degrades the gate to a false `fail` exactly when it is relied upon (the reasoning already recorded in the "Review engine" principle in `specs/architecture-principles.md`). The cross-model value is recoverable on the host when wanted; the security cost of (a) is not recoverable once granted.
- **It matches the cloud decision.** ADR 0001 already recorded that the off-machine loop reviews via **Claude, not Codex**, for the same bwrap/auth reasons. Making the in-container default explicitly Claude keeps the two records coherent.

## Consequences

- **No image privilege change, no new attack surface** on the diff-reviewing container.
- **In-container `--engine codex` is documented as degrading** — an operator who wants a cross-model review runs it on the host, not in the container. The sibling **infra-detection** hardening (a separate ticket) makes an in-container Codex attempt *fail loudly* rather than emit a misleading success; that hardening is independent of this decision and lands regardless.
- **Model-family diversity in review is a host-only capability.** Tracked against the generator/evaluator principle: the in-container gate is single-family (Claude); a deliberate cross-model pass is a host-side `--engine codex` run.

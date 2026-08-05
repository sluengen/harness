# ADR 0013 — Codex runs in-container behind a targeted seccomp profile; the engine is chosen at invocation

- **Status:** Accepted
- **Date:** 2026-08-04
- **Source:** `specs/proposals/codex-engines-and-the-container-sandbox.md`
- **Amends:** [0002](0002-in-container-review-engine.md) (the in-container review engine), [0007](0007-design-verb.md) (design's Claude-only engine)

## Context

ADR 0002 recorded that Codex cannot review in-container — its bundled `bwrap` cannot create a user namespace in the unprivileged `harness:dev` container — and rejected fixing that as "a real, standing security regression," costing the fix as "`CAP_SYS_ADMIN`, `--privileged`, or a custom seccomp profile."

The wall is still real. Measured 2026-08-04 against `harness:dev`, codex-cli 0.146.0 (still shipping `codex-resources/bwrap`, no landlock subcommand), Docker server 29.6.2: baseline `unshare -U` returns `Operation not permitted` and bwrap fails with the literal CAL-866 message.

The cost is not what the ADR recorded:

| Container config | Result |
|---|---|
| baseline | userns blocked; bwrap fails |
| `--cap-add SYS_ADMIN`, default seccomp | userns created, then `bwrap: pivot_root: Operation not permitted` |
| `--security-opt seccomp=unconfined`, no cap-add | userns created, bwrap **rc=0** |

The gate is the seccomp profile alone. `CAP_SYS_ADMIN` — the grant ADR 0002's security argument is actually about — is neither sufficient nor required. Two syscall families do all the blocking: `unshare`/`clone` carrying `CLONE_NEWUSER`, and `pivot_root`.

Two consequences followed from the uncorrected premise. Cross-model review, which `specs/architecture-principles.md` records as available via "a host-side `--engine codex` run," describes an act nobody performs — every tick goes through the wrapper, so the documented escape hatch is unreachable from the only path that runs. And `design`, which spends Opus unconditionally on every run (ADR 0007), has no second engine at all: `DESIGN_ENGINE` is the constant `"claude"` (`harness/cli/design.py:139`).

## Decision

**Codex runs in-container behind a targeted seccomp profile with no capability grant. The engine is selected at invocation, not on the ticket. `design` gains an engine union, sequenced after the sandbox change.**

- **The profile is a delta, not a removal.** `docker/seccomp-codex.json` is Docker's default profile plus `pivot_root` and unconditional `unshare`/`clone`. The container's capability set is unchanged — no `CAP_SYS_ADMIN`, not `--privileged`. `seccomp=unconfined` was rejected: it clears the same gate by removing all syscall filtering, which is a far wider grant than the evidence supports.
- **The security argument is narrower than ADR 0002's, and is the one this decision makes.** The container already holds the ssh key, the tracker token, and a read-write bind mount of the repo. Seccomp is not what protects those from a prompt-injected diff — the engine's own read-only sandbox is, and today that sandbox cannot start, which is why the Codex path degrades rather than protects. Allowing two syscall families to switch it on trades a narrower host-kernel boundary for a working capability boundary around credentials already in reach.
- **The engine is an invocation flag: `/harness run --codex`,** passed through to both engine verbs as `--engine codex`. It answers "which subscription has headroom this hour" — a property of the moment, not of the work — so the hourly tick's thin caller carries it and the ticket carries nothing. One flag covers both verbs because capacity is shared between them.
- **ADR 0005 is not extended.** Its `<dimension>:<tier>` labels carried a per-ticket judgment made at spec-authoring time. An operational capacity toggle is a different question with a different lifetime, and overloading the label carrier would have put a decision that changes hourly onto an artifact that outlives the run. (#321 has since retired those labels outright — for the same underlying reason, that a per-ticket carrier was the wrong home for this kind of value; the engine remains an invocation flag.)
- **Provenance stays on the ledger.** `review` and `design` events already record `engine` (and `model`) generically, so which engine judged a run remains auditable even though the ticket never states it. No schema change.
- **`design`'s engine union lands after the sandbox change has run in anger.** It is the point of the exercise — the unconditional-Opus stage is where the subscription load sits — but nothing downstream of "bwrap starts" is verified yet, and `design` has no fallback engine.

The general rule: **a property of the work goes on the ticket; a property of the moment goes on the invocation.**

## Alternatives rejected

- **Keep Codex host-only (ADR 0002 unchanged).** Rejected because its stated reason does not hold: the measured fix requires no capability grant. The conclusion could still have been re-argued on the narrower ground above, and was — it did not survive, because the container's credentials are already reachable by anything it runs and the read-only engine sandbox is the control that would actually bound an injection.
- **`--security-opt seccomp=unconfined`.** One flag, measured working. Rejected: it removes the entire syscall filter to unblock two families, on a container holding credentials and a writable repo mount. "Allow what is needed" and "allow everything" are not the same grant.
- **`--cap-add SYS_ADMIN`.** Measured **insufficient** — `pivot_root` still fails — so it would need a profile change anyway, while granting the capability the security argument is most concerned about. Strictly worse than the chosen option on both axes.
- **Run the engine host-side, brokered by the ADR 0012 runtime host.** Structurally cleanest and needs no container privilege at all; #308 is already chartered to make the path equivalence it requires real. Rejected as the destination *for now* on two grounds: it puts untrusted diff content in front of an engine running outside the container, a strictly larger threat-model change than a scoped profile; and it depends on the whole #305–#308 chain, none of it started. It remains available later, and this decision does not foreclose it.
- **Per-ticket engine labels.** Rejected with ADR 0005 above — the toggle's lifetime is the tick, not the ticket.

## Consequences

- **The profile lands on `docker/harness-wrapper.sh` and will have to move.** ADR 0012 relocates container construction into `harness serve` (#307) with platform-specific spawn concerns in #308. Doing it now and moving it later is accepted rework, chosen over blocking a one-flag capability behind ten unstarted tickets.
- **A vendored seccomp profile drifts from the daemon's builtin.** The guard must assert behaviour — bwrap starts, and a syscall the profile does not grant stays blocked — never the file's contents.
- **Everything downstream of "bwrap starts" is unverified.** There is no Codex subscription on this machine, so the probe stopped at sandbox init, which is exactly the wall this amends and is measurable without auth. That a full `--engine codex` review completes — auth, model turn, per-command sandboxing across a real review — is untested, and no ticket may claim it without a real run.
- **`design` on Codex has no fallback.** `review` degrades a depleted Codex tier to Claude (CAL-702); ADR 0007's design failure path is degrade-and-record, so a failed Codex design produces *no design* and the run continues without one. The engine-union change must state what happens there, or it trades spend for a stage that silently stops happening.
- **The stdout channel stops being purely a detector.** `design`'s marked-block fallback exists to catch a permission-grant regression no test can reach. If Codex delivers on it normally, `channel='stdout'` must not become unremarkable for Claude.
- **`doctor` will be wrong until updated.** It encodes ADR 0002's conclusion as remediation text rather than probing, so it will report the engine unusable after it becomes usable.

# What this harness assumes the model cannot do

Every component here encodes an assumption about what an agent gets wrong on its
own. When a model release makes one false, the component is waste — and without
this table nothing can retire one, which is how the v5 cull reset a counter and
changed nothing else.

**Read it at every model or host release.** For each row, run the *retirement
test* and record the answer with a date. A row whose test passes is a deletion
candidate for the next `/assess process`, which is where deletions are decided
(P2, P5). A row nobody has tested in a year is itself a finding.

**A row is not permission to keep the thing.** The assumption is the case *for*
the component; the test is what closes it. A component whose assumption cannot
be stated is already waste.

## Hooks

Enforcement, so the assumption is about what instruction alone fails to hold.
The controls of record are branch protection and gate output in CI; a hook is a
cheaper rung that catches the mistake earlier.

| Component | Assumes | Retirement test |
|---|---|---|
| `hooks/gate-evidence-guard.js` | An agent will report a task complete without having run the gate over the tree it authored, because "I ran it earlier" feels sufficient. | Over 50 recorded runs, no completion claim without a fresh marker. Host caveat: Stop-hook blocks are capped at eight, so this was always a nudge. |
| `hooks/git-push-guard.js` | An agent will push to a shared branch on evidence that covers a different tree — a stale marker, or a tree an amend changed. | A release where no run attempts a push the guard refuses for a stale or absent marker. This is also the control of record's local half; retire only with server-side enforcement that reads the same marker. |
| `hooks/push-target-guard.js` | An agent under pressure will reach for `--force` to make a rejected push succeed. | No force-push attempt in a release's recorded runs. Weakest candidate for retirement: the cost of being wrong is rewritten history on a shared branch. |
| `hooks/test-lock-guard.js` | Instruction does not stop test modification: over 79% of measured agent cheating is editing the test directly, despite an explicit rule (ImpossibleBench). | A published benchmark showing test-editing under an explicit instruction at the noise floor. Known gap today: the matcher is `Write`/`Edit`/`apply_patch`, so a `Bash` heredoc or `sed -i` is not seen — measured on this ticket's own run, where every edit went through `Bash` and the hook never fired. |
| `hooks/hooks.json` | The two hosts will not register six hooks per repo by hand, and a hook registered in one repo and not another is a control nobody can rely on. | The host registers a plugin's hooks from the plugin manifest without a second file. Not a model assumption. |
| `hooks/package.json` | Node's module resolution needs the declaration beside the hooks, and `test_hooks_module_type.py` holds it. | Not a model assumption. |
| `hooks/prompt-guard.js` | An agent will act on instructions embedded in content it is writing or has fetched. | Advisory and warn-only. This repo's own standing test for a warn-and-pass guard: **it has not been shown to run until it has fired once for the real reason.** It has not. Retire at the next `/assess process` unless it fires first. |
| `hooks/workflow-guard.js` | An agent will edit source outside a worktree, on a shared branch. | Native worktree isolation confirmed on both hosts (the accepted proposal names this one for retirement already). Advisory; same warn-and-pass test as above. |

## Scripts

The gate and its plumbing. The assumption is about determinism, not judgment: a
script exists where an agent re-deriving the answer each time would drift.

| Component | Assumes | Retirement test |
|---|---|---|
| `scripts/verify.sh` | Nothing about the model. It is the repo's gate — the thing every other row's evidence comes from. | Never retired while the repo ships code. |
| `scripts/gate-marker.js` | An agent cannot bind a claim to a tree oid by hand reliably, and a marker written by prose instruction would be written when the agent felt finished. | A host feature that records verified-tree evidence natively. |
| `scripts/harness-config.js` | Hand-rolled configuration readers disagree with each other: three of them produced #487, #488 and #510. | One reader is not an assumption about the model; retire only if configuration itself goes. |
| `scripts/harness-refs.js` | Agents cannot discover another clone's gate result without an object transfer, so a flat ref is the cheap channel. | A host or forge feature publishing per-tree build evidence readable in one call. |
| `scripts/land.js` | An agent asked to decide the unchanged / clean-merge / conflict landing case from prose will take the wrong branch under pressure, and the wrong branch pushes unreviewed bytes. | A recorded release in which the three cases are taken correctly from prose alone. Bounded: this is the one place where being wrong lands unreviewed code on the integration branch. |
| `scripts/mutate.py` | A guard test that cannot fail is indistinguishable from one that passes, and nothing else in this repo proves the difference. | The evals in T5 cover guard quality. Harness-local: it is not shipped, and a consuming repo uses its language's ecosystem tool (mutmut, Stryker). |
| `scripts/_mutate_outcomes.py` | Rides with `mutate.py`. | Same row. |
| `scripts/build_design_tokens.py` | A hand-copied token value stops tracking its source (ADR 0004). | The design layer goes, or the page stops embedding token values. |
| `scripts/promotion-step.sh` | CI logic inside a workflow `run:` block cannot be executed by a test. | The forge runs a workflow step locally under test. |
| `scripts/setup-cloud-env.sh`, `scripts/session-start-bootstrap.sh` | A fresh container does not carry the toolchain, and a run that discovers that mid-gate reports a red tree for an infrastructure reason. | The execution environment ships the toolchain. |
| `scripts/package.json` | Node's module resolution needs the declaration. | Not a model assumption. |

## Skills

The lifecycle. The assumption is *would the agent get this wrong without it* —
the deletion test — and T5 replaces every row here with a recorded with/without
delta, which is a stronger answer than the judgment below.

| Component | Assumes | Retirement test |
|---|---|---|
| `skills/engineering` | Models write implementation before its test when not stopped, and rationalise it afterwards. | T5's with/without delta at the noise floor. |
| `skills/review-discipline` | A reviewer without a mandate reviews what it notices rather than what was asked, and cannot tell a bug from an improvement without the factual line. | T5's delta, plus the admitted defect classes in its `craft.md` ceasing to recur. |
| `skills/authoring` | A spec written from memory asserts stale facts, and ambiguity is the measured precondition for cheating (0.7–3.4% clear, 22–44% ambiguous — EvilGenie). | A model that grounds and disambiguates unprompted. |
| `skills/architecture` | Design decisions get made in passing and recorded nowhere, so the next change contradicts them. | T5's delta. |
| `skills/work-discovery` | An unattended loop picks the lowest id, or a ticket it cannot finish, without a stated ranking and actionability bar. | The tracker's own ordering answers it, or the loop's picks match a human's over a recorded window. |
| `skills/worktree-isolation` | Agents build on the branch they are standing on. | Native worktree isolation on both hosts — the same test as `workflow-guard.js`, and they retire together. |
| `skills/tracker` | Ticket semantics restated per backend drift apart, and a filing that exits zero is assumed to have landed. | The backends converge on one API, or the host models tickets natively. |
| The nine command workflows — `skills/build`, `skills/review`, `skills/capture`, `skills/propose`, `skills/routine`, `skills/digest`, `skills/assess`, `skills/promote`, `skills/init` | One assumption, nine artefacts: an operator typing the same multi-stage prompt gets a different lifecycle each time, and a stage that ends when the model feels finished ends early. | The host offers durable multi-stage workflows with typed stages and per-stage exit checks. Retire them together or not at all — they share the assumption. |
| `templates/rules/design-system.md` | Guidance that must be triggered by description fires at 53%; a path-scoped rule fires at 100% (research 01 §10). | Description-triggered guidance measured at parity. |

**Two skill-level fields are deliberately not set.** A skill without
`context: fork` that declares `model:` overrides the *session's* model for the
rest of the turn, and `effort:` overrides the session's effort. A domain skill
loaded in the middle of a `/build` would therefore retune the run that loaded
it, so every skill carries `model: inherit` and only the operator-triggered
workflows — which own their whole turn — carry a concrete `effort:`. Retirement
test: a host that scopes both fields to the skill rather than the turn.

## Agents

| Component | Assumes | Retirement test |
|---|---|---|
| `agents/dev` | A builder holding the whole run's context confuses what it planned with what it built. | A model that separates the two reliably in one context. |
| `agents/reviewer` | A reviewer that saw the work being built cannot review it independently; and per ADR 0005, the cheaper model reviews as well as the dearer one (18.4% vs 17.3% fail rate, under the noise floor). | Self-review measured at parity with fresh-context review. |
| `agents/reviewer-feature` | ADR 0005's measurement was over ordinary changes, and does not extend to a contract change or a protected area. | A measurement over feature-lane work showing the same parity. Retire this file the day it does — it exists only for the two lines of frontmatter. |
| `agents/architect` | Design produced inside an implementation context follows the implementation rather than leading it. | T5's delta. |
| `agents/steward` | Cross-file cumulative patterns are invisible to per-change review, whatever the reviewer's quality. | A per-change review that surfaces accumulation. |

## Carried, with an owner — the residual from #547

Four things ship on evidence weaker than the rest, recorded so they are not
mistaken for exercised behaviour.

Each names **who** produces the missing evidence and **when** — a criterion that
names its owner and its moment does not block a PASS (the operator's rule, 2026-09-06).

| What | Why it is carried | Owner, and the moment |
|---|---|---|
| The board writes in `skills/tracker/references/github.md` (item-add, Status, Priority) | Projects v2 is GraphQL-only, and the agent proxy in front of this container refuses every GraphQL query before GitHub sees it — proven not to be a token or scope problem: `gh auth token` returns the same proxy sentinel as `$GH_TOKEN`, and a raw `curl` of `viewer { login }` is refused identically. The recipes moved verbatim from `github-issues`, where they were exercised. | **The operator**, or CI — any session with unrestricted GraphQL. One `create`, re-reading the item's Status and Priority. |
| Every recipe in `skills/tracker/references/linear.md` | No Linear transport and no Linear repo are reachable from this environment. The recipes moved verbatim from the `linear` skill. | **The first consumer update — calibrate**, which has a Linear workspace. Create, transition, hold, Todo placement, ledger append, recorded on #547 then. |
| The `/assess` drain marking every entry done, folded or dropped | `skills/assess/SKILL.md` step 5 forbids an unattended run from draining: the slate needs somebody to answer it. The recipe's correctness is reviewed by reading. | **The operator**, at the first attended `/assess` drain after this lands. |
| Pinning an official MCP transport plugin | The marketplace entries for `github` and `linear` carry no version, so there is nothing to pin to; confirming it by installing one is the operator's call and was not taken. | **The operator**, whenever the transport swap is re-asked at a release. |

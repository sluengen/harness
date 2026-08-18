# Assessment report (the steward's output format)

The shape of a `/assess` report. The steward writes one dated file per pass; `assessment-craft` holds the *craft* (the finding bar, how a finding is placed on the 2×2, the insight-vs-finding test), this holds the *format*. Drop sections a pass does not need; never pad to fill them.

**Filename.** `assessments/<YYYY-MM-DD>-<scope>.md` — e.g. `assessments/2026-06-15-code.md`. The dated `assessments/` directory is the convention; do **not** write `steward-<domain>-<date>.md` at the repo root.

**Retention.** `assessments/` keeps only the **latest report per scope** plus **any report with an open finding**; every other report is *superseded* and folds into a rolling `assessments/LOG.md`, one line each — `- <YYYY-MM-DD> · <scope> · <one-clause verdict> · findings: <resolved / ticketed>`. A finding is *open* until its ticket is closed (or it is otherwise resolved); a report is superseded when it is not the latest for its scope **and** none of its findings are still open. **A retired scope is the one exception to *latest for its scope*:** a report whose scope the current `/assess` can no longer produce is superseded once none of its findings are open — nothing can ever supersede it by being newer, so the open-finding test alone decides, and until it passes the report is still kept. **Never fold away a report that still has an open finding.** This holds the directory to roughly one file per scope plus the live-finding tail — a running index, not a growing pile of point-in-time reports whose findings are already fixed (noise) or tracked in the tracker. `/assess` applies this after committing each report (`commands/assess.md`).

---

# {Scope} assessment — {YYYY-MM-DD}

**Steward:** steward (`{scope}` scope{, `--deep` if run}) · **Base:** `{branch}` @ `{sha}` · **Gate:** {not run — read-only assessment / the verify result if anything changed}.

## Why this pass

One short paragraph: what triggered the assessment and what it set out to read. Ground every later claim in the live tree.

## Verdict

The one- or two-paragraph headline — the state of the scope and where the risk concentrates. State it plainly; this is what a reader skims first.

## Findings

Each finding is a level-3 heading carrying its ID, a one-line title, and (when decided) a disposition. The ID is prefixed by scope — `CODE-` / `ARCH-` — and numbered within the pass.

### {SCOPE}-{n} — {one-line title}

**What:** the specific issue.
**Where:** `file:line` (code) or the section (docs) — a real, clickable reference.
**Why:** the rule, principle, or contract it violates.
**How:** a concrete fix, not "this is wrong".

(Repeat per finding. **Zero findings is a legitimate, stated outcome** — say so plainly and do not invent findings to fill the report.)

## Systemic insights

Up to **three**. An insight is a single concrete edit to a skill, agent, command, hook, or template that stops a *class* of findings from recurring. Each names the exact file and edit and cites at least one finding as evidence. Zero insights is legitimate — write "no insights this cycle" rather than inventing one. An insight is an improvement, so it is **not filed as a ticket**: it is appended to the proposals ledger and decided at the drain (`commands/assess.md`).

### {SCOPE}-INSIGHT-{n} — {one-line title}

The class it prevents, the exact edit (file + change), and the finding(s) it generalises.

---

## Architecture report shape (the `architecture` scope)

An `/assess architecture --deep` pass writes the *same* dated file (`assessments/<YYYY-MM-DD>-architecture.md`) in a **holistic** shape, not a finding list. Its value is the narrative; only the actionable risks leave as tickets (`commands/assess.md`). Use these sections — drop any a pass does not need, never pad to fill them:

- **Verdict** — the one- or two-paragraph headline: is the system shape still right for the product, and where does the risk concentrate?
- **System map / current shape** — the boundaries and major components as they actually stand, so a reader can place everything that follows.
- **What is working** — the positive bets to preserve and the trade-offs worth keeping. **These are not findings and are not filed as tickets** — recording them is the point of a holistic review.
- **Architectural risks** — the actionable concerns, each with the four parts (`assessment-craft`), IDs prefixed `ARCH-`. These *are* filed.
- **Watchlist / triggers** — files or boundaries to add to the repo's `architecture_watchlist` (`skills/architecture/SKILL.md`) so the next change there trips a conditional refactor.
- **Recommended actions** — the concrete changes the risks imply, ordered by leverage.
- **Findings / tickets to file** — the subset above that becomes tracker issues: the actionable risks and recommendations only.
- **Not assessed** — what this pass deliberately did not cover, so the verdict is not read as broader than it is.

**Zero tickets is a valid architecture pass.** A verdict, a watchlist, and a "what is working" section with no filed risk is a useful, complete report — not a failed run.

---

After the report is written, the `/assess` command files each finding as a tracker issue, appends each insight to the proposals ledger, and commits the dated report (`commands/assess.md`). For the `architecture` scope it files **only** the actionable risks and recommendations — never the narrative sections.

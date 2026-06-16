<!-- guidance:template-assessment@0.1.0 -->
# Assessment report (the steward's output format)

The shape of a `/assess` report. The steward writes one dated file per pass; `assessment-craft` holds the *craft* (the finding bar, severity, the insight-vs-finding test), this holds the *format*. Drop sections a pass does not need; never pad to fill them.

**Filename.** `assessments/<YYYY-MM-DD>-<scope>.md` — e.g. `assessments/2026-06-15-system-and-code.md`. The dated `assessments/` directory is the convention; do **not** write `steward-<domain>-<date>.md` at the repo root.

---

# {Scope} assessment — {YYYY-MM-DD}

**Steward:** steward (`{scope}` scope{, `--deep` if run}) · **Base:** `{branch}` @ `{sha}` · **Gate:** {not run — read-only assessment / the verify result if anything changed}.

## Why this pass

One short paragraph: what triggered the assessment and what it set out to read. Ground every later claim in the live tree.

## Verdict

The one- or two-paragraph headline — the state of the scope and where the risk concentrates. State it plainly; this is what a reader skims first.

## Findings

Each finding is a level-3 heading carrying its ID, a one-line title, the severity, and (when decided) a disposition. The ID is prefixed by scope — `CODE-` / `SYSTEM-` — and numbered within the pass.

### {SCOPE}-{n} — {one-line title} — {Critical | High | Medium | Low}

**What:** the specific issue.
**Where:** `file:line` (code) or the section (docs) — a real, clickable reference.
**Why:** the rule, principle, or contract it violates.
**How:** a concrete fix, not "this is wrong".

(Repeat per finding. **Zero findings is a legitimate, stated outcome** — say so plainly and do not invent findings to fill the report.)

## Systemic insights

Up to **three**. An insight is a single concrete edit to a skill, agent, command, hook, or template that stops a *class* of findings from recurring. Each names the exact file and edit and cites at least one finding as evidence. Zero insights is legitimate — write "no insights this cycle" rather than inventing one.

### {SCOPE}-INSIGHT-{n} — {one-line title}

The class it prevents, the exact edit (file + change), and the finding(s) it generalises.

---

After the report is written, the `/assess` command files each finding and insight as a tracker issue and commits the dated report (`commands/assess.md`).

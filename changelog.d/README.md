# Changelog fragments

One file per change: `changelog.d/<ticket>.md`, carrying the entry exactly as it renders in `CHANGELOG.md` — `### <Category> — <summary> (#<ticket>)` and a body. Two runs write two files, so there is nothing to conflict over (#267).

A change with **no ticket by design** — an `/assess` report, a `/propose` output — uses `changelog.d/no-ticket-<slug>.md` and may carry only `### None — <why> (no-ticket-<slug>)` (#287).

Format, exemptions and the release fold: see [`RELEASING.md`](../RELEASING.md).

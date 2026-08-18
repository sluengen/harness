# The proposals ledger

An improvement is proposed, never filed (`review-discipline` → *bugs are filed; improvements are proposed*). The **proposals ledger** is where a proposal lands so it outlives the report that raised it: one standing issue per repo, holding every entry as a comment. It is not a new operation — it composes three the provider skills already have: a scoped list to find it, `create` to open it once, `comment` to append.

**Find it by label, never by number.** This guidance installs into every repo that adopts it, so no repo-specific issue id may appear here and the ledger's address is a label instead: list the repo's open issues carrying the `proposals-ledger` label, and **create it when that search finds none**, applying the same label. Exactly **one open** ledger exists per repo. A search returning two is a tracker configuration error — report it and stop, rather than picking one, because appending to the wrong instance splits the record in a way no later reader can detect.

**Opening the ledger is infrastructure, not filing.** The bugs-only filing rule bounds what an agent may put on the *queue*, and the ledger is never on it: open it **held** — assigned to the operator, carrying the `operator` label — so no unattended tick can pick it, and state in its body that it is a record and is never built directly.

**Entries accumulate as memory, not as promises.** Nothing in the ledger expires, nothing auto-drops, and no entry is owed a build; an entry is what the loop noticed, kept where the operator can find it. `/digest` reads the ledger and surfaces what is new; `/assess` drains it, which is the only thing that clears an entry.

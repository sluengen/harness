<!-- guidance:review-discipline-craft@0.6.1 -->
# Review craft: defect classes that read as green

Load this when the change adds or edits a guard, a prose predicate, a mutation
table, or a deletion pass. Those are the diff shapes where an entirely green
suite is compatible with a shipped defect, and each entry below is a class that
did exactly that. The families not gated on those shapes — *The ticket and its
criteria* and *Unmeasured claims* — apply wherever their subject appears: the
ticket you are building from, and any claim written into prose that nothing
measures.

Every entry has a name, the rule in one line, and a falsifying example — the
concrete shape where the wrong thing read as green. The example is the
load-bearing half; read it to recognise the shape in the diff in front of you.

Additions to this file are raised as a **proposal** for an operator call — an
entry here is an improvement, so it is appended to the proposals ledger with
`craft.md` as its suggested home and decided when `/assess` drains it, never
self-filed. The entry bar here is *a defect class
that reads as green*, which is a standing incentive to grow the file, and every
entry taxes the context of every future reader. The operator is the budget-holder
for that tax.

These extend the core bar, they do not restate it. The finding 2×2, the
final-evidence ordering rule and the reviewer's obligations stay in
`review-discipline`; the fresh-evidence rule stays in `code-quality`; the
test-first law stays in `test-driven-development`; the shape-triggered structural
checks stay in the diff-shape checks.

## Vacuity — the test that cannot fail

### Exercise the production path, not merely a production constant

Import the production *function* and call it. A test that imports the production
constant and re-applies it in its own loop measures the constant, and agrees with
itself about everything else.

**Falsifying example.** A guard read the shipped pattern and re-scanned the
corpus with it. Production applied the same pattern over a different text unit.
Both the real-input assertion and every synthetic control agreed with the guard's
loop, so the suite could not see the scope defect at all. The fix is structural:
one function, called by both the real-input test and the controls, so a change to
how production scans is a change to what every control measures.

### The empty subject set

A parametrized guard whose subject source derives to `[]` collects nothing, and
the run stays green.

**Falsifying example.** A guard parametrized over the tracked files matching a
naming convention. A rename emptied the match, pytest reported
`SKIPPED … got empty parameter set`, and the summary line stayed green. Nothing
in the gate output distinguished "checked every subject" from "checked none".
The companion is an assertion, outside the parametrization, that the subject set
is non-empty.

### The empty comparison set

Worse than the empty subject set: the subjects are fine and every case PASSES,
while the set each case *compares against* derives to `[]`.

**Falsifying example.** A guard collected 72 documents and compared each one's
named types against a set derived by a suffix match. Breaking only the
derivation left all 72 cases passing — no skip, no warning, nothing in the output
to notice. The rule this yields: the non-vacuity companion must assert the set
the comparison **consumes**, not merely that the guard collected cases. "The
guard ran over N subjects" satisfies *The empty subject set* and sails straight
through this one. A guard with both sets needs a floor on each.

### The conditional guard whose skip reads as green

A test written to skip when its subject is absent is correct, and its skip is
indistinguishable from coverage.

**Falsifying example.** A criterion phrased "whenever the artifact exists, the
document must cite it" was implemented as a test that skips when the artifact is
missing. Renaming the artifact made the cite test skip and left the suite green.
Pair every conditional guard with a floor asserting the condition is live today.
That does not weaken the conditionality — it makes retiring the subject a
deliberate edit (delete the floor in the same change) instead of a silent loss.

### The floor inside the parametrization

A non-vacuity floor carried as one more parametrized case vanishes with the set
it was meant to protect.

**Falsifying example.** A guard's floor was written as an extra case in the same
`parametrize` that supplied the subjects. When the subject source derived to
`[]`, the floor went with it: the run reported `1 skipped` and no failure. Put
the floor in its own test function, where an empty subject set cannot delete it.

### Floors decay into decoration

Set a floor just under the measured value, and pin set **membership**, never
length.

**Falsifying example.** A floor of `>= 30` written against a measured 77 stayed
green while whole trees were removed. Separately, a check that a derived tuple
had length three was satisfied forever by `("A", "B", "B")`. Never assert
cardinality as the floor either — a hardcoded count is usually the very drift the
guard exists to remove. Non-empty, plus a named anchor so a rename names itself,
is the form that does not rot.

### A guard over an enumerable dimension must fail on an unclassified member

A guard over an enumerable dimension — file suffixes, defect families, subtrees —
fails on an unclassified member rather than letting it fall through, so the diff
that introduces the novelty answers the coverage question in place or defers it
consciously.

**Falsifying example.** A size ceiling classified tracked files by extension and
walked the trees it knew about. Its one comment prefix was the prefix the repo's
only language used, so on the day it was written every tracked file was covered
and every control was honest. A later change added the tree's first files in a
second language. They matched no classifier, the walker passed over them, and the
ceiling silently stopped applying to a whole language while the guard still
reported green over the files it recognised — the gap surfaced a release later,
as a defect in the guard rather than a question the introducing diff had been
made to answer. The shape to look for is a classifier whose default branch means
*not my subject*: make that branch fail, and the change that brings the new
member is the change that has to place it or record why it does not belong. The
same reading applies to the derived set the classifier feeds — a subtree list, a
family map — which is why this is a vacuity class and not a prose-predicate one:
the assertion holds over a subject that quietly stopped growing.

### A control goes inert when the change deletes what it names

A control that names a path, symbol, or phrase the change removed still reads as
a control while flagging nothing.

**Falsifying example.** A detector's positive control asserted that a synthetic
line citing a module was flagged. The change deleted that module, so the cite
resolved to nothing, the detector returned empty, and the control's assertion
that *nothing* was flagged now passed for the opposite reason. A single teardown
left five controls inert this way. Every control a deletion pass touches needs
re-pointing at a surviving subject of the same shape, and the docstring should
say which subject and why.

### A positive control must exercise the predicate, not re-implement it

The control feeds the production predicate a sample it must judge a certain way,
and it must distinguish the predicate from its cheaper degradation.

**Falsifying example.** A guard needed a *positional* predicate: the defining
first sentence of a comment had to carry a qualifier that already appeared in an
appended tail. A whole-comment containment control passes on the exact defect.
The control that works is fed the pre-fix wording verbatim and asserts two
things: the sample is judged non-compliant, **and** the same sample contains the
word somewhere — the containment half is what makes the rejected weaker
predicate's blind spot explicit. Then mutate the helper, not the data, and
confirm the control is what dies.

### Born green

If the fix and its test landed in one edit, the test never failed. Re-break the
path and watch it go red.

**Falsifying example.** A test written alongside its fix asserted a property the
surrounding code already satisfied for an unrelated reason; reverting the fix
left it green. Watch the first test-first run for an unexpected PASS, not only an
unexpected FAIL — a vacuously passing assertion is the test-first law's quietest
failure mode, and the run where it is cheapest to catch is the first one.

### Reentrancy makes a same-thread assertion unfalsifiable

After widening a lock, semaphore, or other synchronisation primitive, re-check
every test asserting the primitive's own behaviour.

**Falsifying example.** A test acquired a lock, called the code under test, and
asserted the lock was released. Making the lock reentrant meant the assertion
held on the acquiring thread whatever the code did. Observe the release from a
thread that never held the primitive, or the assertion is a tautology about
reentrancy.

### `all()` over a possibly-empty iterable is constant-true

`all(...)` and `not any(...)` over a generator that yields nothing are `True` by
definition.

**Falsifying example.** A guard asserted `all(rule_holds(x) for x in subjects)`
where `subjects` came from a filtered scan. The filter stopped matching and the
assertion became a constant. Assert the iterable is non-empty in the same test,
or collect the violations into a list and assert the list is empty — the list
form at least names what it checked when it fails.

Its sibling is *A comparison whose operands live in different frames is constant*
below: the same symptom, an assertion true for every input, reached the other way.
Here the subject is empty; there both operands exist and are measured against
each other in incommensurable units. Check which of the two you have before
reaching for a remedy — asserting non-emptiness does nothing for a frame
mismatch.

### A comparison whose operands live in different frames is constant

A containment, prefix, or ordering test is constant unless both sides are
expressed in the same frame. Resolve both operands to a common one before
comparing them.

**Falsifying example.** A floor existed to prove a fixture's symlink pointed
*outside* the repository — a link pointing inside is a shape git answers about
happily, and would leave the guard testing nothing new. It asserted
`not link.readlink().is_relative_to(link.parent)`. But `readlink()` returns the
target as written, which is usually relative, and a relative path is never
`is_relative_to` an absolute one; the assertion therefore held for every relative
target, however far inside the repository it pointed. Mutating the fixture to
link at a relative in-repo path survived the entire suite — including the floor
whose sole job was to catch exactly that. Comparing
`(link.parent / link.readlink()).resolve()` against `link.parent.resolve()`
makes that mutation the assertion's exclusive killer.

Paths are the common case in a guard suite that reads a tree, but the shape is
the frame and not the API: a naive datetime compared with an aware one, and a raw
string compared with a normalised one, fail the same way. The tell is an
assertion that reads as a strong claim — `is_relative_to` looks like it measures
containment, and its negation like it measures escape — while one side was never
in a position to satisfy it.

Its sibling above is *`all()` over a possibly-empty iterable is constant-true*,
where the constancy comes from an empty subject instead, and where the remedy is
a non-emptiness assertion rather than a common root.

## Prose predicates and text guards

### A blacklist inversion sweep fails open on an appended grant

A sweep that looks for a forbidden wording catches a *rewritten* rule and misses
an *appended* one, because the original phrasing it keys on is still sitting
there untouched.

**Falsifying example.** A guard checked that a document's prohibition was still
present and that no permissive verb appeared near it. Appending a fresh sentence
granting the exception left the original prohibition intact, so the presence half
still fired and the sweep stayed green. Measured, five of six naturally written
grant wordings survived the blacklist. The fail-closed shape is the inverse: a
whitelist of permitted verbs plus a sweep that requires the negation, so a new
sentence has to *earn* its way past rather than merely avoid a listed word.

### The negation window assumes a false converse

"A negation within N words of the verb" asserts that a nearby negation governs
the verb. It does not.

**Falsifying example.** An intervening modal, or a blocking verb — `preclude`,
`prevent`, `forbid`, `bar`, `rule out` — sits inside the window and flips the
polarity of the clause while both the presence predicate and the inversion sweep
read green in the same direction at once. Bound the window, pin the bound in a
test, and write a control for each blocking verb; an unbounded window lets one
`not` silence every claim after it.

### The text unit is part of the predicate

A sentence-scoped and a paragraph-scoped sweep compute opposite booleans over the
same negation. Choose the unit deliberately and pin it.

**Falsifying example.** Two of them. A splitter that never fires when a sentence
ends inside emphasis merged a rule with everything after it, so a single `Never`
shielded the whole merged span. Separately, a bad split made a document's entire
decisions index parse as one 2,677-character "sentence", letting one `superseded`
excuse the whole span — the sweep reported zero offenders while live. Feed the
controls **synthetic** text spliced into the real document, not a standalone
clean sentence: a control that cannot fail for the reason the real assertion
fails is not a control.

### A paired delimiter can be counterfeited by prose that mentions it

A guard that strips or scopes the region between paired delimiters will open one
on a *mention* of the delimiter in ordinary prose. Anchor the opener to where the
syntax actually admits it, and splice-prove the interior is still reachable.

**Falsifying example.** A sweep for ticket-shaped identifiers stripped fenced
code before reading a document, because the character it keys on is live syntax
inside code and not in a sentence. The strip used the obvious pattern: the fence
marker, a lazy body, the fence marker again. A live guidance file carried a
sentence *mentioning* a fence mid-clause; that mention was read as an opener, and
the strip swallowed 1,355 characters of real prose through to the next genuine
fence, mis-pairing every fence after it. Nothing errored. The scanned corpus
simply got shorter, so the sweep reported zero offenders over text it never
opened, and the guard read green. It surfaced only under three splices: a shape
the predicate was **known** to catch died at one offset, the shape under test
survived at that same offset, and the same shape under test died earlier in the
same file — one conclusion, that the region between the two deaths was
invisible. The remedy is to anchor the opener to line start with indent
tolerance; Python's `re` needs each lookbehind branch fixed-width, so
`(?<![^\n])` rather than `(?<=^|\n)`. It generalises past fences to every paired
delimiter a text guard strips or scopes — HTML and JSX comment markers, a
front-matter rule, a heredoc terminator, a BEGIN/END block — and documentation
*about* a syntax is the structurally most exposed corpus for it, because prose
there reliably carries that syntax's delimiters as its subject matter. This is
the neighbour of *The text unit is part of the predicate*, not an instance of it:
that entry is a splitter reading too much as one unit, remedied by choosing the
unit deliberately and pinning it; this one is the corpus silently shrinking
before any unit is chosen, remedied by anchoring the delimiter and proving by
splice that the interior is reachable. A guard can have both defects at once, and
each remedy leaves the other standing.

### A paraphrase tuple drawn from the sweep's own alternation measures itself

A tuple of paraphrases lifted from the sweep's own release alternation measures
coverage of itself, not robustness against wording nobody has thought of yet.

**Falsifying example.** Measured against independently written permissions, a
full-page sweep caught 6 of 10; the escapes released in an adjective or a
comparative rather than in an enumerated verb — "one image of the entire page is
preferable to slices", "a short page may be captured whole", "prefer a single
full-page image where the surface fits". A report-line sweep caught 0 of 6 — "at
the reviewer's judgment", "recommended but not mandatory", "where it adds value",
"skip … for a docs-only diff", "encouraged", "nothing requires …". Record the
count and the wordings together: a count with a short list beside it invites the
reader to treat the list as the whole escape set, which is the same
self-agreement one level up. Such a tuple is a floor against degrading to
a single-wording check and nothing more; never report it as evidence of
paraphrase completeness, which is the change agreeing with itself in a new place.
The honest disposition is to record the measured escapes **at their size** next
to the predicate. Widening the alternation is not the fix: a blacklist has no
completion condition, and each widening risks flagging the rule it protects.

### Mutate the rule into its opposite, not only out of existence

Deleting a sentence proves a guard sees the sentence. Inverting it proves the
guard sees what the sentence *says*.

**Falsifying example.** A substring guard over a prohibition was killed by
removing the sentence and survived rewriting `must never` to `may`, and survived
`every` becoming `some`. A substring guard over prose is blind to polarity and to
quantifier; both mutations belong in the table.

### Every prose obligation needs a pair with separate exclusive killers

Presence and inversion are two conditions, and two conditions that die to the
same edit hide each other.

**Falsifying example.** Deleting the rule kills the presence assertion alone; a
permissive splice that leaves the rule in place kills the inversion sweep alone.
Written as one combined assertion, either mutation reports a kill and the other
half is never exercised. Write them as separate assertions, then prove each has a
mutation that kills it and leaves the other green.

### Write the rule, then run its own guard over it

A rule's own wording can register as an offender against its own predicate.

**Falsifying example.** A guard banning a phrase carried the phrase in its own
scanned scope and flagged itself — but only once the file was committed, because
the sweep reads the tracked tree. The same trap works in reverse: a rule written
to forbid a permissive verb used that verb to describe what it forbids. Run the
new predicate over the new prose before handing off, and stage the file first.

## Deletion, retirement, and re-homing

### A deletion pass that moves a definition must move its killer

When a definition is re-homed out of a deleted module, its guard is in the
deleted module too. Move both, or the survivor is unguarded.

**Falsifying example.** A teardown re-homed a primitive that six predicates call
and left its only killer behind in the module it deleted. The primitive shipped
guarded by nothing, with the whole suite green. This is the twin of the
wiring-field family: the value survives, the thing that could falsify it does
not. For every symbol a deletion pass relocates, name the test that kills it and
confirm that test relocated too.

### A guard deleted over a surviving subject

The rule is *delete a guard if and only if its subject is gone* — audited
per-guard, not per-grep.

**Falsifying example.** A mass deletion removed 23 guards on the reasoning that
their subjects went with the retired subsystem. Four subjects had survived. One
commit later the change shipped the exact defect one of the deleted guards
forbade, with the gate green throughout. A grep for the subsystem's name is not
the audit; opening each guard and asking what it actually reads is.

### Assert absence from the git index, never by grep

A tracked-file query returning the empty set is the opposite polarity from a text
search, and cannot fail open.

**Falsifying example.** A guard asserting a retired tree was gone grepped for its
name. A typo in the pattern, a path that never matched, or a scan rooted at the
wrong directory all return "no hits" — indistinguishable from success. Ask the
index for the tracked files under the path and assert the set is empty. Always
pair it with a did-not-delete-too-much floor: a pure absence suite passes on an
empty repository.

## Mutation discipline

### The wiring-field survivor

A value threaded onward — into a struct field, a report field, a message arm —
has no exclusive killer, so it survives every mutation while the suite stays
green.

**Falsifying example.** A field was populated, carried through two layers, and
rendered into a report nothing asserted on. Every mutation of the value was
killed by a test asserting a *sibling* field, so the table read clean. And a
wiring field is never one line: it is a family. After a pass finds one gap, sweep
for its twins — every other place the same value is threaded onward — because the
shape repeats wherever the pattern was copied.

### A green mutation table certifies only what its author thought to mutate

N-of-N killed means N *predicted* edits were caught. It is not a statement about
the boundary.

**Falsifying example.** A table of twelve mutations, all killed, over code whose
untested branch nobody thought to mutate. The number reads as completeness and
measures imagination. Report a table as "these N edits are caught", never as
"the guard is complete".

### Never re-run the builder's table as verification

The builder's table is the change agreeing with itself. The reviewer constructs
its own.

**Falsifying example.** Across four consecutive tickets, the reviewer's
independently constructed mutations found live survivors that the builder's
honest, fully-killed table could not — on one of them three survivors, on the
next one. Re-running the builder's table costs the same time and measures
nothing new.

### A survivor is ambiguous

A surviving mutation has four readings — the mutation changed nothing, the code
is genuinely redundant, it defends something no test exercises, or a sibling
assertion already subsumes every shape the tests cover — and choosing between
them is the work.

**Falsifying example.** A document briefed its reader on a reference twice, and
deleting one of the two cites survived every guard, because the assertion was
"the root names the path", not "names it twice". Read as redundancy it says
delete the second brief, which removes a pointer a reader depends on; read as a
coverage gap it says pin the count, which is exactly the cardinality floor that
rots the day a third brief is added. The subsumption reading was the right one,
and the disposition was to record the survivor with its reason rather than act on
it. Reading a survivor as "delete it" by default has removed real defences;
reading it as "add a test" by default has grown suites around dead code. Settle
the inert reading — did the mutation change anything the guard reads — before
spending any thought on the rest, because it voids them; see
*An inert mutation reports a survivor it never earned*.

### An inert mutation reports a survivor it never earned

A mutation that left the subject's behaviour unchanged also reports SURVIVED,
and that reads as a weak guard while being no evidence of one.

**Falsifying example.** An adversarial review filed a blocking finding off a
surviving mutation. The finding was right — the guard did have the gap — and its
proof was invalid, because the mutation never changed anything the guard reads,
so its survival measured nothing. That is the expensive shape: a correct
conclusion resting on an invalid proof passes review on the strength of being
correct, and the next reader inherits both. It is the twin of the false-kill
entry below, and the worse half, because a survivor is the verdict a reviewer is
hoping for. Before citing a survivor against a guard, name the observable that
changed — a differing digest, a differing output, one differing byte. With no
observable the entry is *unproven*, not weak, and a table that cannot tell those
apart is reporting its author's expectations back to them.

### A mutation that changes no behaviour reports a kill it never made

An edit that leaves the original path intact measures nothing, and a red suite
after it is a coincidence.

**Falsifying example.** A mutation inserted an early-return branch above the
original logic without removing it, so the original still ran on every input the
tests supply. The suite went red for an unrelated reason and the mutation was
recorded as killed. Every mutation needs a landing assert (the old text was
found), a containment assert (the edit landed in the intended tree, not a sibling
checkout), and a claim about which behaviour it changed.

### A prose mutation needs a paired splice to prove it was live

When the subject is prose, there is usually no observable to declare — nothing
digests a paragraph — so liveness has to be built into the experiment instead.

**Falsifying example.** A sweep for identifiers of one shape was suspected of
missing a second shape. Splicing only the suspected shape and watching it survive
would have been equally consistent with the sweep never reading that file at all:
a path outside its scope, a directory it excludes, a membership rule that drops
the file one level up. The paired splice separates those — insert a form the
predicate is **known** to catch and the form under test at the same location in
the same file, and require the known form to die first. Same file and same
location is the entire control; a splice that dies somewhere else proves only
that the sweep reads *some* text, not this line. Once the control dies, the
other's survival is a gap rather than an unproven claim, and the finding is sound
by construction where no observable was available to make it sound by
measurement.

### A mispredicted killer is how a guard gap surfaces

Always ask which test *actually* died, not only how many.

**Falsifying example.** A mutation was predicted to kill a specific assertion and
killed a different one instead. The predicted assertion had a gap: it was passing
for a reason unrelated to the property it names. The count was right and the
conclusion was wrong. Record predicted-killer against actual-killer for every row
in the table; the mismatches are the findings.

### Stale bytecode masks a size-preserving mutation

A byte-identical restore can leave the interpreter reusing a cached module, so a
SURVIVED verdict may be an artifact of the cache.

**Falsifying example.** A pure block swap — two branches exchanged, same length,
same mtime granularity — was restored from a backup, and the next run reused the
compiled cache from before the restore. The verdict flipped once the cache was
purged. Purge the bytecode cache between mutation runs, or use an instrument that
guards against it, and treat every same-length mutation as suspect until it is
re-run clean.

### Redundancy needs a mutation only the suspect test can see

To ask whether a test is redundant, find an edit that kills it and nothing else.

**Falsifying example.** A broad mutation killed nine tests including the suspect,
which reads as duplication and is no evidence at all. The differential oracle is
a narrow mutation aimed at the property the suspect test claims to isolate: if
another test kills it too, the suspect is redundant; if nothing else does, it is
the only thing standing between the tree and that defect.

### Two redundant conditions hide each other from mutation

When two conditions in the same predicate catch the same input, mutating either
one alone leaves the predicate correct.

**Falsifying example.** A validator checked both an emptiness condition and a
membership condition that could only fail together on the tested inputs.
Mutating either survived, and the pair read as defended. Mutate both at once to
find out whether the predicate has one condition or two, then delete the one
that carries nothing or add the input that separates them.

## The ticket and its criteria

### A ticket's grounding is its least reliable part

Grep the tree for every named symbol **and every number** in the grounding before
trusting any of it.

**Falsifying example.** A ticket's grounding carried three wrong claims: a
version that had moved, a count that was stale, and a document listed for
retirement that the governing decision explicitly keeps. Stale line numbers,
invented mechanisms, and "the only X" claims that stopped being true are the
usual shapes. Re-derive every cited fact, verify cited *tests* exist rather than
cited line numbers, and amend the ticket before touching a file — the amendment
on the ticket is what keeps the record honest, not a note in the commit body.

### An acceptance criterion can be unsatisfiable by construction

When a criterion's subject is a property of an external tool, no test in this
tree can prove it.

**Falsifying example.** A criterion asserted a behaviour of a tool the repo does
not control and cannot invoke in the gate. Neither quietly weakening it nor
deferring the whole ticket is right. Split it: a gate-provable half that pins
what this tree does own, and an opt-in live half that runs against the real tool
on demand. Then record in the as-built record what the gate does **not** prove,
because that gap is now a property of the shipped record.

### An acceptance criterion can contradict the ticket's own problem statement

When the criteria and the problem statement cannot both hold, the ticket needs a
decision before it needs code.

**Falsifying example.** A criterion blessed an option the problem statement ruled
out. Building the option table first, counting which signals support each, and
shipping the narrower thing is the resolution — with the narrowing named on the
ticket. Silently building to the criterion ships the wrong feature with a green
review; silently deferring the whole ticket loses the confirmed part.

### An acceptance criterion naming a dead artifact

The obligation usually moved. It rarely expired.

**Falsifying example.** A criterion named a file two earlier changes had deleted.
The reflex reading is "this criterion is obsolete, drop it". The obligation had
been re-homed into a different file under a different name, and dropping the
criterion would have shipped the gap the criterion existed to close. Go find the
new home before concluding anything expired.

### The ticket's subject moved because another change built most of it

Measure the tree against the criteria before planning. The residual is the
ticket, not the description.

**Falsifying example.** A ticket arrived with most of its criteria already met by
an intervening change, because each item in the parent breakdown updates the
as-built record for its own change. Closing it unbuilt is the wrong reflex: the
criteria enumerate the surfaces someone thought of at filing time, and the
residue is reliably in files they did not name. Re-measure, then re-scope on the
ticket.

## Unmeasured claims — prose asserting what nothing checks

### A declined action is not a prevented one

A probe that observes an agent or tool *choosing* not to do something has
measured a behavioural mitigation, not a boundary.

**Falsifying example.** A docstring claimed a mode "carries no edit/write/bypass
capability". Measured, that mode had an unrestricted shell tool and a write tool
available, and merely declined the write on every probe. The claim in the
docstring was false, and it was the kind of false claim a later reader builds a
security argument on. State what was observed, and write "declined" wherever you
did not measure "prevented". When a probe matters, also ask the subject to
attempt something it should not be allowed, so a denial is observed rather than
assumed.

### A design's security claim and its mechanism are written by the same optimism

Check the mechanism against the property as a separate act, by a reader who did
not write either.

**Falsifying example.** A design asserted a containment property and specified
the mechanism meant to deliver it. The mechanism could not deliver it, and the
review read the claim and the mechanism as corroborating each other because both
came from the same author in the same document. A design's claims about a tool it
does not control are its weakest part; a few minutes of probing falsified three
of them on one change, and finding them after implementation would have meant a
rewrite.

### A comment asserting an unmeasured precondition

A comment that states a condition the code relies on is a defect waiting for its
second cause. Measure the claim it already makes.

**Falsifying example.** A comment read "safe because the caller always
validates". Nothing asserted that any caller validated, and a second call site
arrived that did not. The comment is free evidence about what the author believed
had to be true — turn each one into an assertion or a test rather than leaving it
as prose.

### A forward reference becomes a lie the day its dependency ships

And it can be born false.

**Falsifying example.** A document cited a section that a later change was
supposed to add. The later change landed with the section renamed, and the
citation pointed at nothing — with no guard, because the citation had been added
as a promise rather than a fact. Either create the fact before this change
merges, or write the sentence so it claims nothing about a future artifact.

### An ordinal reference into an enumeration is invalidated by a correct insertion

A sentence that points at a member of an enumeration by position — "the third
reading", "the last two families" — holds only until something is inserted,
removed, or reordered ahead of it. Name the referent, never its index.

**Falsifying example.** A change inserted a reading at the head of an entry's
four-item enumeration, deliberately, because settling that reading voids the
rest. Every edit involved was correct: the insertion, the ordering rationale,
and the sentence that broke, which had been true when written. Further down, the
entry's worked disposition still read "the third reading was the right one" — and
the third reading was now one the entry itself rejects, so the entry contradicted
its own example. Nothing could see it: no guard reads ordinals, and any predicate
that could would be a pinned count, which rots on the next insertion — the same
trap one level up. The change's own mutation table sat on top of the defect and
mutated that sentence's count back into self-consistency, reporting a clean
survivor; the instrument erased the evidence of the defect it was standing on.
Deletion and relocation each already have an entry under *Deletion, retirement,
and re-homing*. Insertion is the structural edit missing from that set, and the
one where the edit, the text it edits, and the sentence it breaks are each
correct on their own — the defect exists only in the relationship between them.
Any change that inserts into, removes from, or reorders an enumeration re-reads
every sentence downstream that refers to a member by position.

### A docstring claiming coverage the code lacks

An over-claiming docstring is a defect, not commentary.

**Falsifying example.** A guard's docstring said it was "derived from the
document's own headings rather than hand-listed" above a hardcoded two-name
tuple. The next reader trusts the docstring, so a real failure reads as a false
positive and the guard gets loosened instead of fixed. When mutation shows a test
isolates a different property than its docstring claims, rewrite the docstring in
the same change — a docstring asserting a property the guard lacks is the same
class as a text guard asserting a fragment of its rule.

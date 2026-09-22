# Prose

**Load this immediately before writing any substantial prose** — a spec, a design, a decision, a ticket body, a review report, a handoff, a commit body. It was `writing-quality`, a skill of its own, until #547 folded it into `authoring`: the same discipline governs every artefact this skill covers, and a second skill that had to be triggered separately fired only when somebody remembered it.

Eliminate predictable AI writing patterns from prose. Not code or structured data.

**Core rule:** make the minimum effective edit. Preserve the author's terminology, cadence, and useful edge. State the point and trust the reader. Cut a sentence that carries no decision, constraint, evidence, action, or necessary context. Prefer a specific fact to generic importance; replace universal claims with the actual scope.

## Phrases to cut

**Throat-clearing openers.** State the content directly instead.
"Here's the thing", "Here's what/why X", "The uncomfortable truth is", "Let me be clear", "It turns out", "Can we talk about". Any "here's what/this/that" construction.

**Emphasis crutches.** They add no meaning.
"Full stop.", "Period.", "Let that sink in.", "This matters because", "Make no mistake".

**Business jargon → plain word.**
navigate→handle · unpack→explain · lean into→accept · landscape→field · game-changer→significant · deep dive→analysis · double down→commit · circle back→revisit · moving forward→next · elevate→improve · journey→process · unlock→enable · seamless→smooth · world-class→(cut).

**Adverbs, softeners, hedges.**
really, just, literally, genuinely, honestly, simply, actually, deeply, truly, fundamentally, inherently, interestingly, importantly, crucially. Also "at its core", "at the end of the day", "in today's X", "it's worth noting", "when it comes to", "the reality is".

**Generic importance claims.** Name the fact or cut the claim.
"The reasons are structural", "The implications are significant", "The stakes are high", "This is genuinely hard".

## Structural patterns to avoid

- **Binary contrasts** — "Not X. Y." State Y directly; drop the negation.
- **Negative listing** — "Not A, not B, it's C." State C.
- **Dramatic fragmentation** — "Noun. That's it." Use complete sentences.
- **False agency** — "The data tells us", "the decision emerges." Name the actor: someone reads, someone decides.
- **Passive voice** — name who did what. "Mistakes were made" → who made them.
- **Rhetorical setups** — "What if...?", "Think about it:", "Here's what I mean:". Make the point directly.

## Sentence-level rules

- Active voice, clear actors.
- Vary sentence and paragraph length. Two items often beat a forced three.
- No weak starters. Restructure sentences leaning on What/When/Which/How as a crutch; lead with subject or verb.
- Minimise em-dashes; a comma or period usually serves.
- **Anchor a citation on an identifier, never a line number.** A function name, a section heading, a symbol, or a string a reader can `git grep` survives editing; a line number is true only until an earlier hunk shifts the file, so a citation written that way can go stale inside the commit that writes it — and the sentence that is now wrong is one nobody edited. #660 corrected three such citations in a single build and #568 one before it. Where the position is genuinely useful, lead with the identifier and put the line beside it, so the reader has something to search when the number has moved.
- **A numeral beside an enumeration it could be derived from names that enumeration, or gives way to it.** "Four rules follow" above a list of four is a count and a list authored from separate sources, and the next edit moves one of them. Write "the rules below", or name what produces the figure. Where the number carries weight the list does not — a total spanning several documents — keep it and cite the enumeration it came from.

## When to apply

All prose output. **Do not apply to** code, structured data (YAML/JSON), test names, CLI output, or table cells where brevity already governs.

---
*Adapted from [Stop Slop](https://github.com/hardikpandya/stop-slop) (MIT) by Hardik Pandya and [No AI Slop](https://github.com/petergyang/no-ai-slop) by Peter Gyang.*

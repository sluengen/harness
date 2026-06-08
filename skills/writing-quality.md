---
name: writing-quality
description: Use when writing prose for the repo — specs, designs, decisions, copy, commit bodies, handoffs (not code or structured data). Load to eliminate predictable AI writing patterns and state things plainly.
---
<!-- guidance:writing-quality@0.2.0 -->
# Writing Quality

Eliminate predictable AI writing patterns from prose: specs, designs, decisions, copy, commit bodies, handoffs. Not code or structured data.

**Core rule:** remove the layers between idea and reader. State the point. Trust the reader.

## Phrases to cut

**Throat-clearing openers.** State the content directly instead.
"Here's the thing", "Here's what/why X", "The uncomfortable truth is", "Let me be clear", "It turns out", "Can we talk about". Any "here's what/this/that" construction.

**Emphasis crutches.** They add no meaning.
"Full stop.", "Period.", "Let that sink in.", "This matters because", "Make no mistake".

**Business jargon → plain word.**
navigate→handle · unpack→explain · lean into→accept · landscape→field · game-changer→significant · deep dive→analysis · double down→commit · circle back→revisit · moving forward→next · elevate→improve · journey→process · unlock→enable · seamless→smooth · world-class→(cut).

**Adverbs, softeners, hedges.**
really, just, literally, genuinely, honestly, simply, actually, deeply, truly, fundamentally, inherently, interestingly, importantly, crucially. Also "at its core", "at the end of the day", "in today's X", "it's worth noting", "when it comes to", "the reality is".

**Meta-commentary.** The document should move, not announce itself.
"In this section we'll...", "As we'll see...", "Let me walk you through...", "Hint:", "Spoiler:".

**Vague declaratives.** Name the specific thing instead.
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
- Specific over vague. Replace "everyone/always/never" with the actual scope; replace "significant" with the actual impact.

## When to apply

All prose output. **Do not apply to** code, structured data (YAML/JSON), test names, CLI output, or table cells where brevity already governs.

---
*Adapted from [stop-slop](https://github.com/hardikpandya/stop-slop) (MIT) by Hardik Pandya.*

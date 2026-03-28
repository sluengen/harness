# Writing Quality

Eliminate predictable AI writing patterns from prose output. This skill applies to specs, designs, strategies, copy, and any other prose artifacts — not code or structured data.

**Core rule:** Remove unnecessary layers between idea and reader. State the point. Trust the reader.

## Phrases to Remove

### Throat-Clearing Openers

Cut these and state the content directly.

- "Here's the thing:" / "Here's what [X]" / "Here's why [X]"
- "The uncomfortable truth is" / "The truth is," / "The real [X] is"
- "Let me be clear" / "I'll say it again:" / "I'm going to be honest"
- "Can we talk about" / "It turns out"

Any "here's what/this/that" construction is throat-clearing. Cut it.

### Emphasis Crutches

These add no meaning. Delete them.

- "Full stop." / "Period."
- "Let that sink in."
- "This matters because" / "Here's why that matters"
- "Make no mistake"

### Business Jargon

| Avoid | Use instead |
|-------|-------------|
| Navigate (challenges) | Handle, address |
| Unpack (analysis) | Explain, examine |
| Lean into | Accept, embrace |
| Landscape (context) | Situation, field |
| Game-changer | Significant, important |
| Deep dive | Analysis, examination |
| Double down | Commit, increase |
| Circle back | Return to, revisit |
| Moving forward | Next, from now |
| Take a step back | Reconsider |
| Elevate | Improve, raise |
| Journey | Process, experience |
| Unlock | Enable, allow |
| Revolutionise | Change, improve |
| Seamless | Smooth, integrated |
| World-class | (cut — show quality, don't claim it) |

### Adverbs and Softeners

Remove -ly adverbs, softeners, intensifiers, and hedges.

- really, just, literally, genuinely, honestly, simply, actually
- deeply, truly, fundamentally, inherently, inevitably
- interestingly, importantly, crucially

Also cut these filler phrases:

- "At its core" / "At the end of the day"
- "In today's [X]" / "In a world where"
- "It's worth noting" / "When it comes to" / "The reality is"

### Meta-Commentary

The document should move, not announce its own structure.

- "In this section, we'll..." / "As we'll see..." / "Let me walk you through..."
- "The rest of this document explains..." / "I want to explore..."
- "Hint:" / "Plot twist:" / "Spoiler:"
- "You already know this, but" / "But that's another [doc/section]"

### Vague Declaratives

Sentences that announce importance without naming the specific thing. Replace with the specific thing.

- "The reasons are structural" / "The implications are significant"
- "The stakes are high" / "The consequences are real"
- "This is genuinely hard" / "This is the deepest problem"

## Structural Patterns to Avoid

### Binary Contrasts

"Not because X. Because Y." / "It's not X. It's Y." — state Y directly. Drop the negation.

### Negative Listing

"Not A... Not B... It's C." — state C. The reader doesn't need the runway.

### Dramatic Fragmentation

Sentence fragments for manufactured emphasis. "[Noun]. That's it." / "X. And Y. And Z." — use complete sentences.

### False Agency

Giving inanimate things human verbs. "The data tells us" — no, someone reads the data and draws a conclusion. "The decision emerges" — someone decides. Name the actor.

### Passive Voice

Every sentence needs a subject doing something. "X was created" — name who created it. "Mistakes were made" — name who made them.

### Rhetorical Setups

"What if [reframe]?" / "Think about it:" / "Here's what I mean:" — make the point directly.

## Sentence-Level Rules

- **Active voice with clear actors.** Name who does what.
- **Vary sentence and paragraph lengths.** Two items work better than three in a list. Don't stack short punchy sentences.
- **No weak starters.** Restructure sentences starting with What/When/Where/Which/Who/Why/How as a crutch. Lead with the subject or verb.
- **No em-dashes.** Use commas or periods.
- **Specific over vague.** Replace "everyone", "always", "never" with the actual scope. Replace "significant" with the specific impact.

## When to Apply

Apply to all prose output: product specs, design rationale, strategy documents, brand copy, acceptance criteria narrative, ADRs, and communication artifacts.

**Do not apply to:** code, commit messages, structured data (YAML, JSON), test names, CLI output, or table cell values where brevity already governs.

## Attribution

Adapted from [stop-slop](https://github.com/hardikpandya/stop-slop) (MIT License) by Hardik Pandya. Tailored for spec-driven development context.

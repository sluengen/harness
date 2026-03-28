# UX Design

User experience strategy, psychology, and flow design. This skill applies when designing, building, or reviewing any user-facing interface. It covers how humans think and behave — the design-system skill covers how interfaces look.

---

## Understand the Human First

Before building, answer three questions. If the user hasn't provided this context, ask before proceeding.

1. **Who is the person using this?** What are they feeling (stressed, curious, rushed, anxious)? What is THEIR goal — not the business goal? What's their context (mobile, desktop, first-time, power user)?

2. **What is the problem space?** What exists today? What conventions do users already know from similar products? What do other industries do with this same underlying problem?

3. **What are the constraints?** Devices, performance budget, existing design system, content availability, technical limitations.

---

## Design With Psychology

### Cognitive Load

The brain holds ~4 chunks in working memory. Every element competes for that.

- **Progressive disclosure:** show only what's needed for the current step
- **Sensible defaults:** pre-select the most common option
- **Chunking:** group into sets of 3–5 items
- **Recognition over recall:** show options, don't make users remember
- **Consistency:** same action always looks and behaves the same way

### Visual Hierarchy

Users scan in 3 seconds. They don't read. Design for the scan.

- Most important thing first, supporting context second, actions third
- One hero element per view. If everything is emphasised, nothing is
- Left-aligned content gets more attention than right-aligned
- F-pattern for text-heavy pages, Z-pattern for visual pages

### Feedback Loops

Every action needs a response. Silence is the enemy.

- **Immediate:** button press, toggle, checkbox (< 100ms)
- **Progress:** skeleton screens, progress bars for anything > 1 second
- **Completion:** success messages, next steps
- **Error:** what went wrong + why + what to do + preserve user's work

### Decision Architecture

How you present choices changes what people choose.

- **Default bias:** most users accept defaults — make defaults the best option for the user
- **Anchoring:** the first option sets expectations for everything after
- **Choice paralysis:** beyond 5–7 options, decision quality drops (Hick's Law)
- **Commitment escalation:** small yeses lead to big yeses (email before credit card)
- **Loss aversion:** "Don't lose your progress" > "Save your progress" — but don't overuse, chronic loss framing creates anxiety

### Key Laws

- **Hick's Law:** fewer choices = faster decisions
- **Fitts's Law:** important targets = large and close to the cursor
- **Jakob's Law:** users prefer interfaces that work like ones they already know
- **Peak-end rule:** people judge experiences by the peak moment and the ending
- **Gestalt proximity:** items close together are perceived as related

---

## Information Architecture and Flow

### Navigation Principles
- Users should always know: where am I, where can I go, how do I get back
- Breadth over depth: 7 top-level items beats 3 levels of nesting
- Consistent navigation placement across all pages (spatial memory)
- "Where am I?" should be answerable in 1 second on any screen

### Design the Flow, Not Just the Screen
- **Happy path:** the ideal journey from start to finish
- **Edge cases:** 0 items? 1,000 items? Long names? Missing data?
- **Error recovery:** every error needs a clear path back to success
- **Empty states:** the first thing new users see — make it useful, not "no data"
- **Loading states:** skeleton screens (show structure) beat spinners (show nothing)

---

## Flow Patterns

### Onboarding

- **Progressive onboarding (SaaS):** don't front-load setup. Let users explore, introduce features in context.
- **Guided onboarding (complex products):** step-by-step wizard when setup is genuinely required. "Step 2 of 4" — always show progress. One action per step. Let users skip non-essential steps.
- **Value-first onboarding (consumer):** show value before asking for anything.

**Rules:** Time-to-value under 60 seconds. Ask only for what you need right now. The first action should produce a visible result.

### Authentication

- **Login:** email + password baseline. Social login reduces friction. Magic link eliminates passwords. "Remember me" on by default.
- **Signup:** minimise fields. Show password requirements before the user types. Real-time validation, not post-submission error walls.
- **Password reset:** never confirm or deny email existence. Auto-login after reset.

### Dashboards

- Most critical metric largest and top-left
- Answer "is everything okay?" in 3 seconds
- Sparklines for trends, not just current numbers
- Real-time data needs visible refresh timestamps
- Mobile dashboards show top 3 metrics, not everything

### Settings

- Group by topic, not alphabetically
- Most-changed settings at the top
- Auto-save or save all — never save individual fields
- Progressive disclosure: basic visible, advanced collapsed

---

## Content Design Essentials

For detailed copy work, the marketing-comms agent handles brand voice and copy. For quick UX decisions involving text:

- Button labels name the outcome, not the action: "Save Changes" not "Submit"
- Every error answers: what happened + why + what now
- Empty states explain why it's empty and what to do about it
- Confirmation dialogs name both actions specifically, never "Cancel" / "OK"
- Tone matches emotional state: calm for errors, brief for success

---

## Accessibility

Accessibility is UX for everyone — not a separate concern.

- **Touch targets:** 44x44px minimum, 48px ideal
- **Colour contrast:** 4.5:1 for text, 3:1 for large text (WCAG AA)
- **Semantic HTML:** correct elements, not divs with click handlers
- **Keyboard navigation:** every interactive element reachable via Tab
- **Screen readers:** aria-labels, aria-live regions, heading hierarchy
- **Respect preferences:** `prefers-reduced-motion`, `prefers-color-scheme`
- **Colour independence:** never use colour alone to convey meaning
- **Focus indicators:** visible focus ring on ALL interactive elements
- **Form labels:** every input needs a visible, associated label

---

## Motion as Communication

Motion answers questions — it is not decoration.

- **Where did this come from?** (origin animation)
- **What changed?** (state transition)
- **Did my action work?** (feedback)
- **What should I look at?** (attention direction)

Timing: micro-interactions 100–150ms, tooltips 150–200ms, panels 200–300ms, page transitions 300–500ms. Closing is always faster than opening. Never linear easing except for progress bars.

---

## UX Verification Checklist

Run before presenting work. Fix failures before showing anything.

- [ ] New user can understand what to do within 5 seconds?
- [ ] Most important action is visually dominant?
- [ ] Interactive elements are obviously interactive?
- [ ] Every action has visible feedback?
- [ ] Error states are helpful, specific, and recoverable?
- [ ] Works with keyboard only?
- [ ] Loading states use skeletons, not spinners?
- [ ] Empty state is useful, not just "no data found"?
- [ ] Flow handles edge cases (0, 1, many, missing data)?
- [ ] Copy is clear, specific, and actionable?
- [ ] Feels good on mobile, not just "fits"?

---

## Never

- **NEVER** start building without understanding who uses the interface
- **NEVER** present a screen without considering all states (empty, loading, error, success, edge cases)
- **NEVER** ignore mobile — if it doesn't work on a phone, it doesn't work
- **NEVER** use hover as the only way to reveal critical functionality
- **NEVER** hide essential navigation more than one level deep
- **NEVER** create a flow without an escape route at every step
- **NEVER** assume users read — they scan in 3 seconds
- **NEVER** add animation without a communication purpose

---

## Attribution

Adapted from [ux-designer skill](https://github.com/anthropics/claude-code).

---
paths:
  - "scripts/**"
  - "hooks/**"
  - "tests/**"
description: The rules that only bind while editing this repo's executable code.
---

# Executable code in this repo

Loaded when a file under `scripts/`, `hooks/`, or `tests/` is opened. The always-loaded
obligations are in `AGENTS.md`; these are narrower and would be dead weight on every
other task.

## Language and dependencies

- Python under `scripts/` is **standard library only**, and `mypy --strict` passes with
  no ignores.
- The shipped JavaScript — the six hooks, `scripts/gate-marker.js`,
  `scripts/harness-config.js`, `scripts/harness-refs.js`, and `scripts/land.js` — has **no
  dependencies at all**, not even dev ones. It runs from a plugin cache with no install
  step, so a `require` of anything but a Node builtin or a sibling in the same shipped set
  is a runtime failure in a consumer's repo, not a build error here.
- `scripts/gate-marker.js` and `scripts/harness-config.js` are **materialized into consumer
  repos** by `/harness:init`, as a pair, because `verify.sh` invokes the marker helper
  locally. A change to either that assumes this repo's layout ships broken; a change that
  adds a third file to that set is a change to `init`. `harness-refs.js` and `land.js` are
  deliberately **not** in it: they run from the plugin root, like the hooks, and take
  `--repo <dir>` where they need to name a checkout.

## Hooks

- A hook **fails open on its own error** and says so on stderr — a hook that blocks on its
  own bug wedges every tool call in the session, which is worse than one that approves. A
  silent fail-open is the #302 defect: indistinguishable from a deliberate pass-through.
- Failing open never means failing to an **empty** protected set. When the shared reader
  cannot be **loaded**, degrade to the conservative fallback — the state an unadopted repo
  is in — because an empty set approves a push to the integration branch. A throw from
  inside a read takes the hook's ordinary outer catch instead; the guarantee is scoped to
  the load, and saying otherwise would be a claim no test holds.
- Configuration is read through `scripts/harness-config.js` and nowhere else. Three
  hand-rolled copies of that parser produced #487, #488 and #510, and holding two of them
  *equivalent to each other* could not see #488, because both were wrong identically.

## Evidence

- **No per-invocation source may decide the gate command** (ADR 0018): not an operand, not
  argv, not an environment variable — including one naming where a module is loaded from.
  Rewriting a checked-in file is the same local trust domain as rewriting `verify.sh`;
  setting a variable is not.
- A guard asserts a property of the **tracked tree**, never the working directory. Read
  both operands through the index (`git show :<path>`, or `tests._gitutil.indexed_text`) —
  a guard over the working tree passes on bytes that are not the bytes that ship. The one
  carve-out is a guard whose *subject is the gap between them*: `test_seeded_assets_are_tracked.py`
  must read the working tree, because a file that never entered the index is exactly what
  it looks for. Such a guard states that in its docstring; anything else reads the index.
- Prove a guard can fail before trusting it: `scripts/mutate.py`, or a staged probe where
  the guard reads the index and is out of its reach. A guard that has never gone red is a
  claim, not a control.
- Coverage measures `scripts/`; the floor is a ratchet, not a target.

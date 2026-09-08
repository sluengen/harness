# AGENTS.md

> Read this before making any change to the design system. This file is the agent contract.

## What this repo is
A layered, mobile-first design system for a **React Native + Expo** app. Eight layers in `00-` through `07-`, plus `assets/`, `governance/`, and `tooling/`. The structure is a **one-way dependency stack** — see `README.md` and `index.html`.

## Setup (one time)
```bash
npm install
```

## Commands

| Command | Effect |
|---|---|
| `npm run tokens:build` | `03-tokens/tokens.json` → `build/tokens.ts`, `build/tokens.json`, `build/tokens.css` |
| `npm run tokens:watch` | Rebuild on any change under `03-tokens/` |
| `npm run tokens:lint`  | Scan integrated app code for raw hex / unit literals |

The repo verification gate runs **build** and **lint**. Both must pass before review.

## Target platform
React Native + Expo for the shipping iOS and Android app. The build emits a typed TS module (`build/tokens.ts`), flat JSON, and CSS custom properties; the local control plane consumes the CSS output. Native Swift/Kotlin outputs are intentionally not emitted — see `integrations/native-ejection.md` if you ever eject.

## Where each change belongs

| You want to… | Edit this |
|---|---|
| Change a brand colour | `03-tokens/tokens.json` — the **semantic** alias, not the primitive |
| Add a new colour ramp | `03-tokens/tokens.json` under `color.primitive`, then add a semantic alias |
| Adjust spacing | `03-tokens/tokens.json` — `size.semantic.space.*` |
| Add a component to the system | Spec first: `04-primitives/<name>/spec.md` (copy from `_template.md`); then implementation |
| Add a new composition | Spec first: `05-patterns/<name>/spec.md`; then implementation |
| Add a new kind of screen | **Governance review required.** See `governance/contributing.md` |
| Reword in-product copy | `01-voice/microcopy-patterns.md`, then propagate |
| Re-skin the system | Edit semantic aliases in `tokens.json`. **Component code must not be touched.** |

## Hard rules

1. **No raw values in component code.** Hex colours, raw `px`/`pt`/`dp`/`sp` literals, hard-coded radii — all forbidden. The lint enforces it.
2. **Components consume semantic tokens, never primitive values.** Tier-1 primitives are ingredients; only tier-2 / tier-3 are served.
3. **A layer never reaches downward.** Tokens don't reference primitives by file. Primitives don't define their own archetype. Patterns don't invent voice.
4. **Update specs before code.** A primitive PR without an updated `spec.md` is not complete.
5. **Update `CHANGELOG.md`** under `[Unreleased]` for every PR.
6. **Never edit anything under `build/`, and never add a file to it.** `build/` is exactly the published `@ds/tokens` package — `package.json` plus the three regenerated token files, nothing else (ADR-030 D1). `mobile/package.json` resolves `@ds/tokens` as `file:../design/build`, so this directory is a package root inside the shipping app and anything you put in it ships. `tooling/check.test.mjs` asserts the listing and fails on any addition; if you need a new generated artifact, it does not belong here — the control plane derives that kind of thing live.

## Forbidden moves

- Adding a one-off token used by exactly one component → either promote it to semantic, or push it down to the component tier; never invent a top-level primitive for one use.
- Introducing a new archetype inside a feature PR.
- Adding raw colour / size literals "just to test." If no token fits, add the token first.
- Editing the generated output to fix a visual problem.

## How to verify before opening a PR
1. `npm run tokens:build` succeeds.
2. `npm run tokens:lint` passes.
3. `governance/review-checklist.md` — every applicable box is ticked.
4. `CHANGELOG.md` has an entry under `[Unreleased]` with the version bump that would apply.

## Integration entry points
| Surface | Read first |
|---|---|
| React Native + Expo (primary) | `integrations/react-native/README.md` |
| Local control plane | `integrations/web/README.md` |
| Ejected native (rare) | `integrations/native-ejection.md` |

## When stuck
- Open `index.html` for the visual map.
- Each layer's `README.md` explains its scope.
- `03-tokens/how-it-works.md` explains the build pipeline.
- `governance/glossary.md` defines every coined term.

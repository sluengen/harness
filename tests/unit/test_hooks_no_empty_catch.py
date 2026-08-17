"""THE-49 (nano-erp) — distributed hook scripts must carry no empty ``catch`` block.

The guidance hook scripts in ``hooks/`` are vendored into consuming repos and
tracked in their ``.guidance-lock.yaml``. A consuming repo whose verify gate runs
ESLint over ``hooks/`` fails on ESLint's ``no-empty`` rule (part of the
``@eslint/js`` recommended config) for every empty ``catch {}`` block — errors the
repo never introduced. This surfaced in nano-erp, which had to exclude ``hooks/``
from its ESLint config as a workaround.

The harness's own gate is Python-only, so it never exercises ESLint — which is
exactly why the empty catches slipped through. This guard closes that blind spot:
it measures the same failure mode ESLint's ``no-empty`` reports for a catch block,
so a future empty ``catch {}`` fails the harness gate at source rather than a
downstream consumer's gate.

An empty catch stays legitimate here — these are advisory best-effort file writes
(state, debounce markers) where a write failure is deliberately ignored. The fix
is to *document* the swallow with a comment inside the block, which both satisfies
``no-empty`` (a comment makes the block non-empty) and records the intent, per the
"errors are never swallowed unexplained" principle in ``engineering-principles``.

Acceptance criteria:

* **AC** — no ``hooks/*.js`` file contains an empty ``catch`` block.
  :func:`test_no_empty_catch_blocks_in_hooks`.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_HOOKS_DIR = REPO_ROOT / "hooks"

#: Matches a ``catch`` block whose body is empty — ``catch {}``, ``catch (e) {}``,
#: ``catch {  }``, or a catch whose braces enclose only whitespace/newlines. This
#: is precisely what ESLint's ``no-empty`` reports for a catch clause (which does
#: not flag empty function bodies or object literals).
_EMPTY_CATCH = re.compile(r"catch\s*(?:\([^)]*\))?\s*\{\s*\}")


def _empty_catches(source: str) -> list[str]:
    """Return the matched empty-catch snippets in ``source`` (empty if none)."""
    return _EMPTY_CATCH.findall(source)


def test_detector_is_non_vacuous() -> None:
    """The detector actually flags an empty catch (guards against a no-op regex)."""
    assert _empty_catches("function f() { try { g(); } catch {} }")
    # A documented catch (a comment inside) and a value-returning catch are clean.
    assert not _empty_catches("try { g(); } catch { /* best-effort */ }")
    assert not _empty_catches('try { g(); } catch { return ""; }')


def test_no_empty_catch_blocks_in_hooks() -> None:
    """No distributed hook script carries an empty ``catch`` block (AC)."""
    hooks = sorted(_HOOKS_DIR.glob("*.js"))
    assert hooks, f"expected hook scripts under {_HOOKS_DIR}"
    offenders = {
        hook.name: matches
        for hook in hooks
        if (matches := _empty_catches(hook.read_text()))
    }
    assert not offenders, (
        "hooks/*.js must not contain an empty `catch {}` block — ESLint's `no-empty` "
        "(in @eslint/js recommended) errors on it in any consuming repo that lints "
        "hooks/. Document the deliberate swallow with a comment inside the catch. "
        f"Offenders: {offenders}"
    )

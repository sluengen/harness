"""The visual-evidence channel's decision — #361, change 1 of 2.

For a change to a user-facing surface, ``review`` is asked whether the result
looks right and structurally cannot look: the engine runs read-only with no
browser, no display and no network. The builder *can* look, and until now that
evidence was discarded at handoff. This module is the decision half of handing it
over — the third member of the evidence family ``--design-file`` and
``--gate-exit``/``--gate-log`` already belong to, where the orchestrator produces
evidence the verb cannot produce itself and the verb records whether it reached
the engine.

Captures are referenced by **absolute path**, never inlined. The design reaches
the prompt as text because text can be inlined; an image cannot, and the engine's
own read-only file access is what opens it. Spiked before this was designed: with
``claude -p --permission-mode plan``, a ``Read`` of a PNG comes back as an
**image content block** — the model receives pixels.

The posture, in one sentence
----------------------------
*A refusal is for what the caller must fix in the invocation — an unreachable
path, an oversized set, an engine that cannot see; everything about the content
of a reachable, in-budget directory degrades and records.* That is
``resolve_design_gate``'s "enforcement refuses; context degrades" with the
refusal half widened by exactly two cases, and this module is deliberately that
function's twin: pure, no ledger, no Typer, returning a small record the verb
acts on.

===========================================  ====================================
Input                                        Outcome
===========================================  ====================================
flag absent                                  proceed, ``not_supplied``
``--engine codex`` with the flag             **refuse** ``screenshots_unsupported_engine``
outside the workspace allowlist              **refuse** ``screenshot_dir_outside_workspace``
an entry or manifest resolving outside it    **refuse** ``screenshot_dir_outside_workspace``
more than :data:`MAX_SCREENSHOTS` images     **refuse** ``too_many_screenshots``
missing, or not a directory                  degrade, ``unreadable``
no matching images                           degrade, ``no_images``
non-image files                              ignored silently
``manifest.md`` absent                       proceed, warn
===========================================  ====================================

Why codex refuses rather than degrades
--------------------------------------
Codex cannot see images. In the #361 spike it reached the right answer only by
shelling out to ``magick``, and ``harness:dev`` carries no ``magick``,
``convert``, ``identify``, ``tesseract`` or PIL. Accepting the combination would
produce a pass that reads as though the reviewer looked, which is the one failure
this channel must not manufacture. The decision is made from **argv alone** — no
ledger read, no filesystem — which is why the verb makes it before every
short-circuit.

Why the cap refuses rather than truncates
-----------------------------------------
Truncating would hand the reviewer a subset while the ``review`` event recorded
that the images were passed: the same manufactured-confidence failure. The
remedy ("narrow the set") is actionable, so it refuses. Twelve is #362's
reference set — roughly four widths (1440/1280/834/390) across up to three pages.

Bounded against an untrusted tree
---------------------------------
The reviewed worktree is untrusted, so enumeration is ``iterdir()`` at the **top
level only** — never a recursion, never an image's content, never a ``stat`` for
size (``review_pollution``'s posture, for the same reason). That is also the
AC-4 cost property: the prompt's growth is a function of the number of paths and
nothing else, which is what "referenced by path, never inlined" *means* once it
is measurable.

The workspace allowlist is the only boundary and is reused whole — the same
``HARNESS_WORKSPACE_ROOTS`` check every verb's ``--repo`` passes — applied to the
directory, **to every entry, and to the manifest**. The per-entry call is what
closes the symlink escape: :meth:`Path.resolve` follows links before the
descendant comparison, so ``shots/evil.png -> /etc/passwd`` normalises outside
and refuses, while a link resolving *inside* the workspace is accepted. The
boundary is the mount, not the link.

The manifest is named separately because it is the asymmetric case, and the
asymmetry runs the wrong way for anyone reading casually. A capture is bounded
but its content is **never** read; the manifest is the one entry whose bytes are
read and placed in the prompt, and the suffix filter passes over ``.md`` before
the per-entry loop ever sees it. Left to the directory's own check it would be
the single member of an untrusted directory able to carry an arbitrary host file
into the review, so it gets the boundary explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from harness.cli.review_protocol import Engine
from harness.workspace import WorkspaceNotAllowed, resolve_within_allowlist

__all__ = [
    "MANIFEST_FILENAME",
    "MANIFEST_MAX_BYTES",
    "MAX_SCREENSHOTS",
    "SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON",
    "SCREENSHOTS_UNSUPPORTED_ENGINE_REASON",
    "SCREENSHOT_EXTENSIONS",
    "TOO_MANY_SCREENSHOTS_REASON",
    "VisualContextReason",
    "VisualEvidence",
    "resolve_visual_evidence",
]

#: What counts as a capture. Compared against a lower-cased suffix, so ``b.PNG``
#: from a Windows or macOS capture step is not silently dropped.
SCREENSHOT_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})

#: The most captures one review may carry — #362's reference set (~4 widths x up
#: to 3 pages). Exceeding it refuses; see the module docstring for why.
MAX_SCREENSHOTS: int = 12

#: The optional manifest, read from inside the capture directory so the whole
#: channel stays one path argument.
MANIFEST_FILENAME: str = "manifest.md"

#: The manifest is untrusted prompt content of unbounded length, so it is capped
#: rather than trusted. Truncation is marked, never silent.
MANIFEST_MAX_BYTES: int = 8192

#: A screenshot path resolves outside the workspace mount. **New, not a reuse**
#: of ``design_file_outside_workspace``: the *check* is reused whole, but reusing
#: the tag would name ``--design-file`` on a ledger row where no design file was
#: passed — the same argument ``polluted_worktree`` makes for staying distinct
#: from ``engine_timeout``.
SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON = "screenshot_dir_outside_workspace"

#: ``--engine codex`` was combined with captures the codex engine cannot read.
SCREENSHOTS_UNSUPPORTED_ENGINE_REASON = "screenshots_unsupported_engine"

#: More captures than :data:`MAX_SCREENSHOTS`.
TOO_MANY_SCREENSHOTS_REASON = "too_many_screenshots"

#: Why a review proceeded WITHOUT visual context, when it did — the twin of
#: :data:`~harness.cli.review_protocol.DesignContextReason`. ``not_supplied``: no
#: ``--screenshot-dir``. ``unreadable``: a path was given that is not a readable
#: directory. ``no_images``: a directory with no matching captures in it.
VisualContextReason = Literal["not_supplied", "unreadable", "no_images"]


class VisualEvidence(BaseModel):
    """What a ``--screenshot-dir`` resolved to.

    One refusal (``refusal_reason`` + ``refusal_message``), or a set of absolute
    ``images`` with an optional ``manifest``, or neither — proceed with no visual
    context, which is what an absent flag or an empty directory earns. A
    ``warning`` may accompany the last case, and ``context_reason`` always does,
    naming *why* nothing reached the engine — absent only when ``images`` is
    non-empty.
    """

    refusal_reason: str | None = None
    refusal_message: str | None = None
    images: tuple[str, ...] = ()
    manifest: str | None = None
    context_reason: VisualContextReason | None = None
    warning: str | None = None


def _read_manifest(path: Path) -> str | None:
    """The capture manifest's text, capped at :data:`MANIFEST_MAX_BYTES`.

    ``None`` when there is none, or when it cannot be read — an unreadable
    manifest is the same as an absent one for every purpose here, and errors
    reading optional enrichment must not fail a review the captures alone can
    inform.

    Takes the **already-bounded** path rather than the directory, by
    construction: the manifest is the one entry whose *content* leaves the mount
    and enters the prompt, so it may only ever be read through a path
    :func:`resolve_within_allowlist` has already accepted. Handing this function
    a directory would put the ``/ MANIFEST_FILENAME`` join — the step that
    escapes — on the far side of the boundary check.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) <= MANIFEST_MAX_BYTES:
        return raw.decode("utf-8", errors="replace")
    head = raw[:MANIFEST_MAX_BYTES].decode("utf-8", errors="replace")
    return f"{head}\n\n[manifest truncated at {MANIFEST_MAX_BYTES} bytes]\n"


def _refuse(reason: str, message: str) -> VisualEvidence:
    return VisualEvidence(refusal_reason=reason, refusal_message=message)


def resolve_visual_evidence(
    screenshot_dir: Path | None, *, engine: Engine, roots: list[Path]
) -> VisualEvidence:
    """Decide what ``--screenshot-dir`` gives this review.

    ``roots`` is :func:`harness.workspace.allowed_roots`' output — already
    normalized. An empty list is the fail-closed state and refuses every
    directory, so a native invocation without the Docker wrapper (which pins the
    allowlist itself) never reaches an engine with paths the container was not
    given.

    The order of the checks is load-bearing:

    1. **no flag** — the ordinary shape, and the only one that is not about a
       path at all;
    2. **the engine** — decided from argv alone, so it is answered before
       anything touches a filesystem, and it owes the message even when the path
       is *also* wrong (a codex run with a perfect path still refuses);
    3. **the boundary**, on the directory;
    4. **readability**, which degrades;
    5. **the boundary again**, on every entry *and on the manifest* — the
       symlink escape;
    6. **the cap**, last, because a security refusal outranks a budget one.
       Reported as a budget refusal, an escape's remedy reads "narrow the set",
       which the caller can satisfy by deleting twelve innocent captures and
       leaving the link.
    """
    if screenshot_dir is None:
        return VisualEvidence(context_reason="not_supplied")

    if engine != "claude":
        return _refuse(
            SCREENSHOTS_UNSUPPORTED_ENGINE_REASON,
            f"--screenshot-dir was supplied with --engine {engine}, which cannot "
            f"read images: the codex engine receives a file read as text, so a "
            f"capture reaches it as bytes it cannot see. Accepting the "
            f"combination would record a pass that reads as though the reviewer "
            f"looked at the rendering. Review with --engine claude, or drop "
            f"--screenshot-dir.",
        )

    try:
        directory = resolve_within_allowlist(screenshot_dir, roots)
    except WorkspaceNotAllowed as exc:
        return _refuse(
            SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON,
            f"--screenshot-dir {screenshot_dir} resolves to {exc.path}, which is "
            f"not reachable under the workspace root(s) this container can read "
            f"({_roots_desc(exc.roots)}). The engine could not open the captures "
            f"there — stage them inside the repo tree (e.g. under the worktree), "
            f"not a host-only path like /tmp.",
        )

    try:
        # ``list`` inside the ``try``, and deliberately NOT ``sorted``: the
        # ordering guarantee belongs to the resolved tuple below, and sorting
        # here would make the test that proves it (which forces ``iterdir`` to
        # yield reverse-lexicographic) pass whether or not the sort survives.
        listing = list(directory.iterdir()) if directory.is_dir() else None
    except OSError:
        # ``is_dir()`` answering yes does not make the listing succeed: the
        # directory may be unreadable, or removed between the two calls. Both
        # are the same caller-visible condition as "not a directory", and this
        # module degrades on the content of a reachable path rather than raising
        # out of a pure resolver — the posture ``_read_manifest`` already takes.
        listing = None
    if listing is None:
        return VisualEvidence(
            context_reason="unreadable",
            warning=(
                f"--screenshot-dir {screenshot_dir} is not a readable directory "
                f"(it does not exist, is a file, or cannot be listed). Reviewing "
                f"without visual evidence — point it at the directory the "
                f"capture step wrote."
            ),
        )

    resolved: list[str] = []
    for entry in listing:
        if entry.suffix.lower() not in SCREENSHOT_EXTENSIONS:
            continue
        try:
            target = resolve_within_allowlist(entry, roots)
        except WorkspaceNotAllowed as exc:
            return _refuse(
                SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON,
                f"the capture {entry} resolves to {exc.path}, outside the "
                f"workspace root(s) this container can read "
                f"({_roots_desc(exc.roots)}) — a symlink leaving the mount. "
                f"Stage the captures themselves inside the repo tree.",
            )
        # After the boundary, never before: a directory named ``page.png``, or a
        # link whose target does not exist, is not a capture — but asking that
        # question first would let a dangling link *out of the mount* answer
        # "not a file" and be dropped silently instead of refused. The stat is
        # on the resolved path, so nothing outside the boundary is ever touched.
        if not target.is_file():
            continue
        resolved.append(str(target))

    # The manifest's boundary, with the entries' and before the cap, because a
    # security refusal outranks a budget one for this entry exactly as it does
    # for the captures. Bounded here, read below — the suffix filter above
    # ``continue``s past ``.md``, so this is the only check it ever gets, and it
    # is the one entry whose bytes reach the engine.
    try:
        manifest_path = resolve_within_allowlist(directory / MANIFEST_FILENAME, roots)
    except WorkspaceNotAllowed as exc:
        return _refuse(
            SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON,
            f"the capture manifest {directory / MANIFEST_FILENAME} resolves to "
            f"{exc.path}, outside the workspace root(s) this container can read "
            f"({_roots_desc(exc.roots)}) — a symlink leaving the mount. Unlike "
            f"the captures, the manifest's text is read and placed in the review "
            f"prompt, so a link out of the mount would carry that file's contents "
            f"into the review. Stage the manifest inside the repo tree.",
        )

    if len(resolved) > MAX_SCREENSHOTS:
        return _refuse(
            TOO_MANY_SCREENSHOTS_REASON,
            f"--screenshot-dir {screenshot_dir} holds {len(resolved)} captures; "
            f"the limit is {MAX_SCREENSHOTS}. They are refused rather than "
            f"truncated: passing a subset while the ledger records that the "
            f"captures were supplied is the manufactured confidence this channel "
            f"exists to avoid. Narrow the set to the widths and pages the change "
            f"actually affects.",
        )

    if not resolved:
        return VisualEvidence(
            context_reason="no_images",
            warning=(
                f"--screenshot-dir {screenshot_dir} holds no captures "
                f"({', '.join(sorted(SCREENSHOT_EXTENSIONS))}). Reviewing without "
                f"visual evidence."
            ),
        )

    manifest = _read_manifest(manifest_path)
    return VisualEvidence(
        # Sorted by resolved path so the prompt is deterministic across
        # filesystems: ``iterdir`` order is whatever the directory hands back.
        images=tuple(sorted(resolved)),
        manifest=manifest,
        warning=(
            None
            if manifest is not None
            else (
                f"--screenshot-dir {screenshot_dir} has no {MANIFEST_FILENAME}. "
                f"The captures are passed anyway (the manifest is optional), but "
                f"without one the reviewer cannot tell a deliberate deviation "
                f"from an unnoticed one."
            )
        ),
    )


def _roots_desc(roots: list[Path]) -> str:
    return ", ".join(str(r) for r in roots) if roots else "none configured"

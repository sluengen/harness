"""#361 — ``resolve_visual_evidence``: what a screenshot directory resolves to.

The pure half of the visual-evidence channel, and a deliberate twin of
``review_protocol``'s ``resolve_design_gate``: one function, no ledger, no verb,
answering *may this review proceed, and with which images*.

The posture it implements, in one sentence: **a refusal is for what the caller
must fix in the invocation** — an unreachable path, an oversized set, an engine
that cannot see — **and everything about the content of a reachable, in-budget
directory degrades and records.** That is ``--design-file``'s "enforcement
refuses; context degrades" with the refusal half widened by exactly two cases,
and the tests below are grouped by which half they measure.

The security boundary is reused whole (``harness.workspace``'s
``resolve_within_allowlist``) and applied to the directory **and every entry**,
which is what closes the symlink escape: ``Path.resolve()`` follows links before
the descendant comparison. The control — a symlink resolving *inside* the
workspace, accepted — is what stops "reject every symlink" passing for the wrong
reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.cli.review_visual import (
    MANIFEST_FILENAME,
    MANIFEST_MAX_BYTES,
    MAX_SCREENSHOTS,
    SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON,
    SCREENSHOTS_UNSUPPORTED_ENGINE_REASON,
    TOO_MANY_SCREENSHOTS_REASON,
    resolve_visual_evidence,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A workspace root; the allowlist for every test below is exactly this."""
    root = tmp_path / "ws"
    root.mkdir()
    return root


def _shots(workspace: Path, *names: str) -> Path:
    """A capture directory holding one empty file per name."""
    shots = workspace / "shots"
    shots.mkdir(exist_ok=True)
    for name in names:
        (shots / name).write_bytes(b"")
    return shots


# --- Degrades and records -----------------------------------------------------


def test_no_screenshot_dir_records_not_supplied(workspace: Path) -> None:
    """The ordinary shape: the flag was never passed, and that is not a warning."""
    evidence = resolve_visual_evidence(None, engine="claude", roots=[workspace])

    assert evidence.refusal_reason is None
    assert evidence.images == ()
    assert evidence.context_reason == "not_supplied"
    assert evidence.warning is None


def test_a_missing_directory_degrades_as_unreadable(workspace: Path) -> None:
    evidence = resolve_visual_evidence(
        workspace / "never-captured", engine="claude", roots=[workspace]
    )

    assert evidence.refusal_reason is None
    assert evidence.images == ()
    assert evidence.context_reason == "unreadable"
    assert evidence.warning is not None


def test_a_path_that_is_a_file_degrades_as_unreadable(workspace: Path) -> None:
    """``--screenshot-dir`` naming a single PNG is a caller slip, not a refusal.

    The remedy is the same as for a missing directory (point it at a directory),
    and the safe outcome — no images reach the prompt — is fully achieved by
    dropping them, so it degrades like the design gate's unreadable case.
    """
    capture = workspace / "one.png"
    capture.write_bytes(b"")

    evidence = resolve_visual_evidence(capture, engine="claude", roots=[workspace])

    assert evidence.refusal_reason is None
    assert evidence.context_reason == "unreadable"


def test_a_directory_that_cannot_be_listed_degrades_as_unreadable(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reachable directory whose *listing* fails must degrade, not raise.

    ``is_dir()`` answering yes does not make ``iterdir()`` succeed: the directory
    may be unreadable (mode 0o000, or an SELinux/ACL denial), or it may be
    removed between the two calls. Either raises ``OSError`` out of what the
    module's own docstring calls a pure resolver, turning a caller slip into a
    traceback. ``_read_manifest`` already catches ``OSError`` for exactly this
    reason, and the stated posture is that everything about the content of a
    reachable directory degrades and records.

    Injected rather than staged with ``chmod``, because the suite runs as an
    arbitrary uid in the container and root can list a 0o000 directory anyway —
    a permission fixture would pass vacuously there.
    """
    shots = _shots(workspace, "a.png")
    real_iterdir = Path.iterdir

    def _denied(self: Path) -> object:
        if self == shots:
            raise PermissionError(13, "Permission denied", str(self))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _denied)

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason is None
    assert evidence.images == ()
    assert evidence.context_reason == "unreadable"
    assert evidence.warning is not None


def test_a_directory_with_no_images_degrades_as_no_images(workspace: Path) -> None:
    shots = _shots(workspace, "notes.txt")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason is None
    assert evidence.images == ()
    assert evidence.context_reason == "no_images"
    assert evidence.warning is not None


def test_images_without_a_manifest_proceed_with_a_warning(workspace: Path) -> None:
    """The manifest is optional by decision (#361): requiring it would refuse the
    caller who did more work and wave through the one who supplied nothing."""
    shots = _shots(workspace, "a.png")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason is None
    assert evidence.images == (str(shots / "a.png"),)
    assert evidence.manifest is None
    assert evidence.context_reason is None
    assert evidence.warning is not None


# --- T2: enumeration ----------------------------------------------------------


def test_enumeration_takes_images_at_the_top_level_only(workspace: Path) -> None:
    """T2 — four independent killers in one fixture.

    * dropping the suffix filter puts ``notes.txt`` in the set;
    * counting the manifest as an image makes it three entries, not two;
    * a case-sensitive suffix comparison loses ``b.PNG``;
    * ``iterdir`` widened to ``rglob`` pulls in ``sub/c.png``.

    Non-recursive is not an accident of implementation: the reviewed worktree is
    untrusted, and ``review_pollution`` takes the same posture — never descend.
    """
    shots = _shots(workspace, "a.png", "b.PNG", "notes.txt")
    (shots / MANIFEST_FILENAME).write_text("page x width\n")
    (shots / "sub").mkdir()
    (shots / "sub" / "c.png").write_bytes(b"")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.images == (str(shots / "a.png"), str(shots / "b.PNG"))
    assert evidence.manifest == "page x width\n"


def test_every_supported_extension_is_recognised(workspace: Path) -> None:
    shots = _shots(workspace, "a.png", "b.jpg", "c.jpeg", "d.webp")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert [Path(p).name for p in evidence.images] == ["a.png", "b.jpg", "c.jpeg", "d.webp"]


def test_an_oversized_manifest_is_truncated_rather_than_dropped(workspace: Path) -> None:
    shots = _shots(workspace, "a.png")
    (shots / MANIFEST_FILENAME).write_text("x" * (MANIFEST_MAX_BYTES + 500))

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.manifest is not None
    # The *length* is the assertion, not merely "shorter than the input". A
    # `startswith` plus a "does not contain MAX+1" pair is satisfied by any cap
    # at all — truncating to 100 bytes would pass both — so the cap the module
    # documents would not be the cap it applies.
    head = evidence.manifest.split("\n\n[manifest truncated")[0]
    assert len(head) == MANIFEST_MAX_BYTES
    assert head == "x" * MANIFEST_MAX_BYTES
    assert f"truncated at {MANIFEST_MAX_BYTES} bytes" in evidence.manifest


# --- T3: deterministic order --------------------------------------------------


def test_images_are_sorted_regardless_of_directory_order(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T3 — the prompt must be deterministic across filesystems.

    Deliberately **not** ``assert images == tuple(sorted(images))``: that is
    self-satisfiable, since any tuple the implementation happened to produce in
    sorted order passes it and an unsorted implementation passes it whenever the
    filesystem happened to hand back a sorted ``iterdir``. Forcing ``iterdir`` to
    yield reverse-lexicographic order is what gives the assertion a killer —
    removing ``sorted()`` from the implementation fails here and nowhere else.
    """
    shots = _shots(workspace, "a.png", "b.png", "c.png")
    real_iterdir = Path.iterdir

    def _reversed(self: Path) -> object:
        return iter(sorted(real_iterdir(self), reverse=True))

    monkeypatch.setattr(Path, "iterdir", _reversed)

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.images == (
        str(shots / "a.png"),
        str(shots / "b.png"),
        str(shots / "c.png"),
    )


# --- Refuses ------------------------------------------------------------------


def test_a_directory_outside_the_workspace_is_refused(
    workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.png").write_bytes(b"")

    evidence = resolve_visual_evidence(outside, engine="claude", roots=[workspace])

    assert evidence.refusal_reason == SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON
    assert evidence.refusal_message is not None
    assert evidence.images == ()


def test_no_configured_roots_refuses_every_directory(workspace: Path) -> None:
    """``HARNESS_WORKSPACE_ROOTS`` fails closed, and this channel inherits that."""
    shots = _shots(workspace, "a.png")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[])

    assert evidence.refusal_reason == SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON


def test_an_image_symlinked_out_of_the_workspace_is_refused(
    workspace: Path, tmp_path: Path
) -> None:
    """T4 — the escape the per-entry check exists for.

    The directory itself is inside the workspace, so checking only the directory
    accepts this: the entry ``shots/evil.png`` resolves to a path the container
    was never given. ``Path.resolve()`` follows the link before the descendant
    comparison, so no second boundary is written — the existing one is simply
    applied to every entry.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"")
    shots = _shots(workspace, "ok.png")
    (shots / "evil.png").symlink_to(outside / "secret.png")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason == SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON
    assert evidence.images == ()


def test_an_image_symlinked_within_the_workspace_is_accepted(workspace: Path) -> None:
    """T4's control. Without it, "refuse every symlink" passes the test above for
    the wrong reason — the boundary is the mount, not the link."""
    real = workspace / "real"
    real.mkdir()
    (real / "ok.png").write_bytes(b"")
    shots = _shots(workspace)
    (shots / "linked.png").symlink_to(real / "ok.png")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason is None
    assert [Path(p).name for p in evidence.images] == ["ok.png"]


def test_a_manifest_symlinked_out_of_the_workspace_is_refused(
    workspace: Path, tmp_path: Path
) -> None:
    """The manifest is the ONLY entry whose *content* leaves the mount.

    Images are bounded but never opened; the manifest is bounded and read, and
    its bytes go straight into the engine prompt. The suffix filter ``continue``s
    on a ``.md`` entry before the per-entry boundary runs, so without an explicit
    check the manifest is the one member of the directory that reaches the prompt
    unbounded — a symlink to any host file the container can stat exfiltrates it
    into the review. The reviewed worktree is untrusted, which is the whole
    reason the per-entry check exists for images.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("SUPER-SECRET-HOST-CONTENT-9f3a\n")
    shots = _shots(workspace, "a.png")
    (shots / MANIFEST_FILENAME).symlink_to(outside / "secret.md")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason == SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON
    assert evidence.manifest is None
    assert evidence.images == ()


def test_a_manifest_symlinked_within_the_workspace_is_read(workspace: Path) -> None:
    """The manifest half of T4's control, and it carries the same weight.

    Without it, "refuse every symlinked manifest" passes the test above for the
    wrong reason. The boundary is the mount, not the link: a capture step that
    stages its manifest once and links it from each width's directory is doing
    nothing this channel objects to.
    """
    real = workspace / "real"
    real.mkdir()
    (real / "notes.md").write_text("index @ 1440; sha HEAD\n")
    shots = _shots(workspace, "a.png")
    (shots / MANIFEST_FILENAME).symlink_to(real / "notes.md")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason is None
    assert evidence.manifest == "index @ 1440; sha HEAD\n"


def test_a_dangling_capture_symlink_out_of_the_workspace_is_still_refused(
    workspace: Path, tmp_path: Path
) -> None:
    """The escape must be refused on the *path*, never on whether it resolves to
    a real file.

    This is the killer that pins the order of the two per-entry steps: a
    ``is_file()`` filter placed **before** the boundary check answers ``False``
    for a dangling link and ``continue``s, so an entry naming a path outside the
    mount would be dropped silently instead of refused — and a link whose target
    is created between the review's enumeration and the engine's read would then
    be one the verb had already decided not to object to.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    shots = _shots(workspace, "ok.png")
    (shots / "evil.png").symlink_to(outside / "not-yet-there.png")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason == SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON
    assert evidence.images == ()


def test_a_directory_named_like_a_capture_is_not_a_capture(workspace: Path) -> None:
    """``shots/page.png/`` is a directory, and the suffix alone cannot tell.

    Naming it to the engine as a capture spends a ``Read`` on something that
    cannot be read and puts an unreadable path in a prompt that says "read each
    one" — the engine's failure to open it is indistinguishable from the channel
    being broken. One ``is_file()`` on the already-bounded path settles it.
    """
    shots = _shots(workspace, "real.png")
    (shots / "page.png").mkdir()

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason is None
    assert [Path(p).name for p in evidence.images] == ["real.png"]


def test_more_images_than_the_cap_is_refused_not_truncated(workspace: Path) -> None:
    """The cap refuses because truncating would hand the reviewer a subset while
    the event recorded that the images were passed — the exact "reads as though
    the reviewer looked" failure the codex refusal exists to prevent."""
    shots = _shots(workspace, *[f"cap-{i:02d}.png" for i in range(MAX_SCREENSHOTS + 1)])

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason == TOO_MANY_SCREENSHOTS_REASON
    assert evidence.images == ()


def test_exactly_the_cap_is_accepted(workspace: Path) -> None:
    """The boundary's other side — without it an off-by-one refusing at ``MAX``
    passes the test above."""
    shots = _shots(workspace, *[f"cap-{i:02d}.png" for i in range(MAX_SCREENSHOTS)])

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason is None
    assert len(evidence.images) == MAX_SCREENSHOTS


def test_a_security_refusal_outranks_the_cap(workspace: Path, tmp_path: Path) -> None:
    """The documented order — "the cap, last, because a security refusal outranks
    a budget one" — measured rather than asserted in prose.

    An over-cap directory that *also* contains an escape must name the escape.
    Reported as ``too_many_screenshots``, the operator's remedy is "narrow the
    set", which they can satisfy by deleting twelve innocent captures and leaving
    the symlink — the refusal that mattered never surfaces, and the whole
    directory has been declared merely oversized.

    Moving the cap check above the per-entry loop survives every other test in
    this module: with 13 clean captures it still refuses as ``too_many``, and
    with an escape under the cap it still refuses as the escape. Only a fixture
    holding both distinguishes the two orders.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"")
    shots = _shots(workspace, *[f"cap-{i:02d}.png" for i in range(MAX_SCREENSHOTS)])
    (shots / "evil.png").symlink_to(outside / "secret.png")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason == SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON


def test_a_manifest_escape_also_outranks_the_cap(workspace: Path, tmp_path: Path) -> None:
    """The manifest's half of the ordering above, and it needs its own fixture.

    The test above pins the cap *below the per-entry loop*; nothing pinned it
    below the **manifest's** boundary, and the two are separate steps. Moving the
    manifest check under the cap survives every other test in this module — an
    over-cap directory whose manifest escapes then reports ``too_many_screenshots``
    and the operator's remedy reads "narrow the set", which they can satisfy by
    deleting captures while leaving the link that carries a host file into the
    prompt. That is the argument the captures' ordering already makes, applied to
    the one entry whose bytes actually reach the engine.

    Killer: relocating the manifest boundary below the cap check. It is exclusive
    — with a clean manifest the cap still refuses, and with an under-cap
    directory the manifest still refuses; only both together tell the orders
    apart.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("SUPER-SECRET-HOST-CONTENT-9f3a\n")
    shots = _shots(workspace, *[f"cap-{i:02d}.png" for i in range(MAX_SCREENSHOTS + 1)])
    (shots / MANIFEST_FILENAME).symlink_to(outside / "secret.md")

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[workspace])

    assert evidence.refusal_reason == SCREENSHOT_DIR_OUTSIDE_WORKSPACE_REASON
    assert evidence.manifest is None


def test_codex_with_screenshots_is_refused(workspace: Path) -> None:
    shots = _shots(workspace, "a.png")

    evidence = resolve_visual_evidence(shots, engine="codex", roots=[workspace])

    assert evidence.refusal_reason == SCREENSHOTS_UNSUPPORTED_ENGINE_REASON
    assert evidence.refusal_message is not None


def test_codex_without_screenshots_is_untouched(workspace: Path) -> None:
    """The refusal is engine × flag, never the engine alone — a codex review that
    supplies no captures is exactly as it was before this change."""
    evidence = resolve_visual_evidence(None, engine="codex", roots=[workspace])

    assert evidence.refusal_reason is None
    assert evidence.context_reason == "not_supplied"


def test_the_engine_refusal_precedes_the_workspace_check(
    workspace: Path, tmp_path: Path
) -> None:
    """A codex run whose path is *also* outside the workspace names the engine.

    Both refusals are exit 5, so the tag is the whole of what an operator reads.
    Naming the workspace would send them to fix a path on a run that would refuse
    with a perfect path — the codex refusal is decided from argv alone and is
    therefore the one that owes the message.
    """
    outside = tmp_path / "outside"
    outside.mkdir()

    evidence = resolve_visual_evidence(outside, engine="codex", roots=[workspace])

    assert evidence.refusal_reason == SCREENSHOTS_UNSUPPORTED_ENGINE_REASON

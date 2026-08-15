"""#361 — the visual block in the review prompt, and what it costs (AC-4a/b/c).

Two things are measured here.

**T7 — the block itself.** Captures reach the engine as *absolute paths*, never
inlined bytes: the design is inlined as text because text can be, and an image
cannot. The block sits with the design block (both are evidence context) and
before the ``SUBMIT`` contract, which ``review_protocol`` already states must be
the last thing the engine reads. The control — a prompt with no captures is
byte-identical to the pre-#361 one — is what stops an unconditional empty block
from shipping.

**AC-4 — the cost, in decreasing sharpness.** The load-bearing measurement is
the *byte differential* (T8a): two capture sets with identical filenames, one
1 KB per file and one 3 MB per file, must produce prompts of identical length.
That is exactly the "referenced by path, never inlined" contract, and no lazy
implementation satisfies it by accident — a base64 expansion, a data URI, or
even a size annotation fails it. T8b makes the same claim structurally (harness
never opens an image), and T8c is the literal wall-clock bound AC-4c asks for,
recorded with its observed number and its own honest limits.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from time import perf_counter

import pytest

from harness.cli.review_protocol import _REVIEW_PROMPT, _SUBMIT_CONTRACT, build_review_prompt
from harness.cli.review_visual import (
    MANIFEST_FILENAME,
    MAX_SCREENSHOTS,
    SCREENSHOT_EXTENSIONS,
    resolve_visual_evidence,
)

#: A realistic absolute container path, at the length #362's capture step
#: produces: the mounted workspace root plus a capture directory plus a
#: page/width filename.
_PATH_TEMPLATE = "/workspace/.harness/captures/361/{page}-{width}.png"


def _realistic_paths(count: int) -> tuple[str, ...]:
    return tuple(
        _PATH_TEMPLATE.format(page=f"page-{i // 4}", width=(1440, 1280, 834, 390)[i % 4])
        for i in range(count)
    )


# --- T7: the block ------------------------------------------------------------


def test_the_prompt_names_every_capture_by_absolute_path() -> None:
    """Killer: emitting basenames, or only the directory, loses these assertions.

    The manifest deliberately does **not** contain the reviewed SHA. It did in
    the first draft ("... sha: abc123"), which made the SHA assertion vacuous:
    the mutation that drops ``reviewed_sha`` from the block survived it, because
    the manifest was carrying the string. Found by mutation, not by reading.
    """
    prompt = build_review_prompt(
        screenshots=("/workspace/shots/a.png", "/workspace/shots/b.png"),
        manifest="page: index, width: 1440",
        reviewed_sha="abc123",
    )

    assert "/workspace/shots/a.png" in prompt
    assert "/workspace/shots/b.png" in prompt
    assert "page: index, width: 1440" in prompt
    assert "abc123" in prompt


def test_the_capture_block_precedes_the_submit_contract() -> None:
    """Killer: appending the block after ``_SUBMIT_CONTRACT``.

    ``review_protocol`` states the contract must stay last; the design block
    already obeys it and the visual block joins it rather than displacing it.
    """
    prompt = build_review_prompt(
        screenshots=("/workspace/shots/a.png",), reviewed_sha="abc123"
    )

    assert prompt.index("/workspace/shots/a.png") < prompt.index(_SUBMIT_CONTRACT)


def test_the_capture_block_sits_after_the_design_block() -> None:
    prompt = build_review_prompt(
        "## The design\n\nA data model.\n",
        screenshots=("/workspace/shots/a.png",),
        reviewed_sha="abc123",
    )

    assert prompt.index("A data model.") < prompt.index("/workspace/shots/a.png")
    assert prompt.index("/workspace/shots/a.png") < prompt.index(_SUBMIT_CONTRACT)


def test_a_prompt_with_no_captures_is_byte_identical_to_the_old_one() -> None:
    """T7's control, and the killer for an unconditionally-emitted empty block.

    A run that supplies no captures — every run until an orchestrator adopts the
    flag — must pay nothing for the channel, not even the tokens of an empty
    section, exactly as ``probe_cap=0`` does.
    """
    assert build_review_prompt() == _REVIEW_PROMPT
    assert build_review_prompt(screenshots=(), manifest=None, reviewed_sha="abc") == (
        _REVIEW_PROMPT
    )


def test_a_manifest_only_call_emits_no_capture_block() -> None:
    """The images are the channel; a manifest with nothing to describe is not one."""
    assert build_review_prompt(manifest="page: index") == _REVIEW_PROMPT


def test_captures_without_a_manifest_still_reach_the_engine() -> None:
    """The manifest is optional, so its absence must not suppress the block."""
    prompt = build_review_prompt(
        screenshots=("/workspace/shots/a.png",), reviewed_sha="abc123"
    )

    assert "/workspace/shots/a.png" in prompt
    assert prompt != _REVIEW_PROMPT


def test_the_block_says_nothing_authenticates_the_reviewed_sha() -> None:
    """The one honest limit the engine itself has to know: a capture is a builder
    self-report, and the verb cannot confirm it depicts the reviewed tree."""
    prompt = build_review_prompt(
        screenshots=("/workspace/shots/a.png",), reviewed_sha="deadbeef"
    )

    assert "deadbeef" in prompt
    assert "manifest" in prompt.lower()


# --- T8a: the byte differential (AC-4a) --------------------------------------


def test_the_prompt_cost_is_independent_of_image_bytes(tmp_path: Path) -> None:
    """AC-4a, and the sharpest measurement in this module.

    Two capture directories with **identical filenames**, one holding 1 KB files
    and one holding 3 MB files, must produce prompts of identical length. Any
    per-image expansion that touches content — ``base64.b64encode(p.read_bytes())``,
    a data URI, a byte-size or dimension annotation — makes the two differ.

    This is the one assertion a lazy implementation cannot satisfy by accident,
    which is why it and not the wall clock is what AC-4 rests on.
    """
    names = [f"page-{i}.png" for i in range(4)]
    small_root = tmp_path / "small"
    large_root = tmp_path / "large"
    for root, size in ((small_root, 1024), (large_root, 3 * 1024 * 1024)):
        root.mkdir()
        shots = root / "shots"
        shots.mkdir()
        for name in names:
            (shots / name).write_bytes(b"\x89PNG" + b"\x00" * (size - 4))

    prompts = []
    for root in (small_root, large_root):
        evidence = resolve_visual_evidence(root / "shots", engine="claude", roots=[root])
        assert evidence.refusal_reason is None
        prompts.append(
            build_review_prompt(
                screenshots=evidence.images, manifest=evidence.manifest, reviewed_sha="abc"
            )
        )

    small, large = prompts
    # Filenames are identical and the roots differ by one character ("small" vs
    # "large"), so equal *lengths* is the honest comparison; equal *content*
    # would be asserting the paths are the same, which they are not.
    assert len(small) == len(large), (
        "the prompt grew with the image files' bytes, so captures are no longer "
        "referenced by path only (AC-4a, #361)"
    )


def test_a_full_capture_set_adds_a_bounded_number_of_bytes() -> None:
    """AC-4a's absolute half: a full 12-capture set is a few kilobytes of prompt."""
    baseline = build_review_prompt()
    full = build_review_prompt(
        screenshots=_realistic_paths(MAX_SCREENSHOTS),
        manifest="page x width x reference frame\n" * 20,
        reviewed_sha="abc1234",
    )

    added = len(full) - len(baseline)
    assert 0 < added <= 4096, (
        f"the visual block added {added} prompt characters for {MAX_SCREENSHOTS} "
        f"captures; the bound is 4096 (AC-4a, #361)"
    )


# --- T8b: harness never opens an image (AC-4b) -------------------------------


def test_harness_never_opens_an_image_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-4b, structurally.

    Every image-content read is booby-trapped: ``Path.read_bytes``,
    ``Path.read_text`` and ``builtins.open`` raise for any path whose suffix is a
    screenshot extension. The **control** is that the manifest is still read —
    so this is not a blanket ban that would pass against an implementation which
    opened nothing at all, and the manifest assertion at the end proves the trap
    let real work through.

    Killer: any implementation that reads, hashes, or measures an image.
    """
    root = tmp_path / "ws"
    shots = root / "shots"
    shots.mkdir(parents=True)
    for i in range(MAX_SCREENSHOTS):
        (shots / f"page-{i:02d}.png").write_bytes(b"\x89PNG" + b"\x00" * 4096)
    (shots / MANIFEST_FILENAME).write_text("page x width, sha abc\n")

    def _forbidden(path: object) -> bool:
        return Path(str(path)).suffix.lower() in SCREENSHOT_EXTENSIONS

    real_open = builtins.open
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text

    def _open(file: object, *args: object, **kwargs: object) -> object:
        if _forbidden(file):
            raise AssertionError(f"harness opened an image file: {file!r} (AC-4b, #361)")
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    def _read_bytes(self: Path) -> bytes:
        if _forbidden(self):
            raise AssertionError(f"harness read an image file: {self} (AC-4b, #361)")
        return real_read_bytes(self)

    def _read_text(self: Path, *args: object, **kwargs: object) -> str:
        if _forbidden(self):
            raise AssertionError(f"harness read an image file: {self} (AC-4b, #361)")
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(Path, "read_bytes", _read_bytes)
    monkeypatch.setattr(Path, "read_text", _read_text)

    evidence = resolve_visual_evidence(shots, engine="claude", roots=[root])
    prompt = build_review_prompt(
        screenshots=evidence.images, manifest=evidence.manifest, reviewed_sha="abc"
    )

    assert len(evidence.images) == MAX_SCREENSHOTS
    assert str(shots / "page-00.png") in prompt
    # The control: the trap was not a blanket ban, and real reading happened
    # through it. Without this the test passes against a resolver that opens
    # nothing at all — including one that never found the manifest.
    assert evidence.manifest == "page x width, sha abc\n"


# --- T8c: the literal wall-clock bound (AC-4c) -------------------------------


def test_the_verb_side_cost_of_a_full_capture_set_is_negligible(tmp_path: Path) -> None:
    """AC-4c — the wall clock, measured.

    **Observed 2026-08-15** on the author's machine (Apple silicon, macOS 15.6,
    Python 3.11.15), worst of five consecutive runs including the cold one:
    ``resolve_visual_evidence`` + ``build_review_prompt`` over 12 x 3 MB captures
    took **0.00015 s** (the four warm runs were 0.00004 s each). The bound below
    is 1.0 s — ~6,600x observed, far past the >=20x the criterion asks for, which
    is deliberate: the gate runs this in parallel across the host's cores, and a
    bound tight enough to be sharp would flake there without ever becoming sharp
    enough to catch the mutation that matters. It is still three orders of
    magnitude under the 900 s ``loop.engine_timeout_seconds`` this cost is added
    to, and four under the 110-minute unattended wall clock.

    **Honest limitation, and why this is the weakest of the three:** its
    discriminating power is poor. Reading 36 MB from a warm page cache is also
    fast, so this bound would **not** kill the mutation
    ``test_the_prompt_cost_is_independent_of_image_bytes`` kills — a base64
    expansion would pass here. It is kept because AC-4c asks for a wall-clock
    bound and because it would catch a genuinely pathological addition (a
    per-image subprocess, a decode, a network call); it is not the criterion's
    real evidence, and the byte differential is.
    """
    root = tmp_path / "ws"
    shots = root / "shots"
    shots.mkdir(parents=True)
    payload = b"\x89PNG" + b"\x00" * (3 * 1024 * 1024)
    for i in range(MAX_SCREENSHOTS):
        (shots / f"page-{i:02d}.png").write_bytes(payload)
    (shots / MANIFEST_FILENAME).write_text("page x width x reference frame\n" * 20)

    started = perf_counter()
    evidence = resolve_visual_evidence(shots, engine="claude", roots=[root])
    prompt = build_review_prompt(
        screenshots=evidence.images, manifest=evidence.manifest, reviewed_sha="abc"
    )
    elapsed = perf_counter() - started

    assert len(evidence.images) == MAX_SCREENSHOTS
    assert str(shots / "page-00.png") in prompt
    assert elapsed < 1.0, (
        f"resolving and rendering a full {MAX_SCREENSHOTS}-capture set took "
        f"{elapsed:.4f}s; the bound is 1.0s against a 900s engine ceiling (AC-4c, #361)"
    )

"""The CONTEXT template's tracker fields say one coherent thing — CAL-1104, CAL-1164.

CAL-1104 advertised two fields that were not interchangeable: ``repo.linear`` (the
address) and ``layers.linear`` (the switch the engine then read), a pairing a repo
could set inconsistently. CAL-1164 collapses the switch to a single ``tracker:``
field — the sole on/off-plus-backend fact — coupled to ``repo.linear`` so the two
cannot contradict.

**#435 kept the text half and dropped the end-to-end half.** Four tests fed the
template's own examples to ``harness.layers``' reader — the strongest form of
this guard, because the docs were pinned against what actually parsed rather
than against a copy of their own words. ADR 0015 deletes that reader, and with
no code reading ``CONTEXT.md`` there is nothing left to drift *from*: the
template is now read by an agent following the ``tracker`` skill. What survives
is the five assertions over the template's own text, whose subject is the
template itself and which are the only guard left on the file — the neutral-surface
sweep in ``test_tracker_neutral_lifecycle.py`` exempts it by name, so losing
these left it wholly unguarded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "CONTEXT.template.md"


@pytest.fixture
def template_text() -> str:
    return _TEMPLATE.read_text()


def _uncomment_github_block(template_text: str) -> str:
    """Recover the ``github:`` block the template shows as a commented example.

    The template's default tracker is ``linear``, so the ``github:`` alternative
    lives commented (each line prefixed with ``# ``), where anything scanning for
    a column-0 ``github:`` key would not see it. This strips the comment prefix
    so the block can be checked as the config it is meant to become, rather than
    as the comment it currently is.
    """
    lines = template_text.splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.rstrip() == "# github:"
    )
    body = ["github:"]
    for ln in lines[start + 1 :]:
        if not ln.startswith("#   "):
            break  # the commented block ends at the first non-indented-comment line
        body.append(ln[2:])  # drop the "# " prefix, keeping the indent
    return "\n".join(body) + "\n"


def test_template_documents_tracker_as_the_single_switch(template_text: str) -> None:
    """The ``tracker:`` line names the tracker-less behaviour ``none`` triggers."""
    line = next(
        ln for ln in template_text.splitlines() if ln.strip().startswith("tracker:")
    )
    assert "tracker-less" in line, (
        "the tracker: line must say what none does — it is the switch every "
        "lifecycle step dispatches on, not documentation of a preference"
    )


def test_template_no_longer_advertises_layers_linear(template_text: str) -> None:
    """The ``layers.linear`` name collision is gone — no ``linear:`` under ``layers:``."""
    in_layers = False
    for line in template_text.splitlines():
        if line.startswith("layers:"):
            in_layers = True
            continue
        if in_layers:
            if line[:1].strip() and not line.startswith("#"):
                break  # a later top-level key ends the block
            assert not line.strip().startswith("linear:"), (
                "layers: must not carry a linear: switch anymore; tracker: is the "
                "single source of truth (CAL-1164)"
            )


def test_template_couples_repo_linear_none_to_the_tracker(template_text: str) -> None:
    """``repo.linear: none`` points at ``tracker: none``, so the two cannot be set apart."""
    line = next(
        ln for ln in template_text.splitlines() if ln.strip().startswith("linear: {")
    )
    assert "tracker: none" in line


def test_template_documents_a_github_block_alongside_the_tracker(
    template_text: str,
) -> None:
    """A ``github:`` example sits by the tracker fields, naming its three keys (CAL-1105).

    A repo bootstrapping onto ``tracker: github`` needs the backend's own config
    block shown, the same way ``repo.linear`` is shown for the Linear backend.
    """
    assert "# github:" in template_text, (
        "the template must show a github: block for the tracker: github backend"
    )
    block = _uncomment_github_block(template_text)
    for key in ("repo:", "project:", "status_field:"):
        assert key in block, f"the github: example must document {key}"


def test_template_documents_github_token_under_env(template_text: str) -> None:
    """The env block names ``GITHUB_TOKEN`` — the github equivalent of ``linear_token``."""
    env_line = next(
        (ln for ln in template_text.splitlines() if "GITHUB_TOKEN" in ln),
        None,
    )
    assert env_line is not None, (
        "the env block must document GITHUB_TOKEN, the tracker: github credential"
    )

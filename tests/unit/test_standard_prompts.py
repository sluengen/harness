"""Tests for the standard prompt library — analyze/implement/review/summarize.j2.

See SPEC §3 (line 140) for directory layout, §5 (lines 416, 439) for usage in
workflows, and §14 (lines 1055-1130) for the steward example exercising
``analyze.j2`` and ``review.j2``.

These tests render templates with a local Jinja2 ``Environment`` to verify
shape, parameterisation, and the ``submit_<node_id>`` tool reference. They do
NOT depend on ``harness/workflow/prompt.py`` (still a stub for a separate
issue).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined, UndefinedError

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "standard"

TEMPLATES = ["analyze.j2", "implement.j2", "review.j2", "summarize.j2"]

REQUIRED_VARS: dict[str, dict[str, str]] = {
    "analyze.j2": {"task": "Read auth.py and summarise the JWT validation flow"},
    "implement.j2": {"task": "Add a null-check around session.user_id in handler.py"},
    "review.j2": {"criteria": "Correctness, test coverage, regression risk"},
    "summarize.j2": {"subject": "the changelog between v1.2 and v1.3"},
}


def _env() -> Environment:
    """Jinja2 env mirroring the runtime: strict undefined, no autoescape."""
    return Environment(
        loader=FileSystemLoader(PROMPTS_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )


# ---------------------------------------------------------------------------
# File presence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_file_exists(name: str) -> None:
    path = PROMPTS_DIR / name
    assert path.is_file(), f"missing standard prompt template: {path}"


# ---------------------------------------------------------------------------
# Rendering — required vars supplied → success
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_renders_with_required_vars(name: str) -> None:
    env = _env()
    template = env.get_template(name)
    rendered = template.render(**REQUIRED_VARS[name])
    assert rendered.strip(), f"{name} rendered empty"
    assert len(rendered) > 50, f"{name} rendered output suspiciously short"


@pytest.mark.parametrize("name", TEMPLATES)
def test_rendered_output_has_no_leftover_jinja(name: str) -> None:
    env = _env()
    rendered = env.get_template(name).render(**REQUIRED_VARS[name])
    for marker in ("{{", "}}", "{%", "%}"):
        # Header comments use {# ... #} and are stripped at render time;
        # statement/expression markers leaking into output mean a typo.
        assert marker not in rendered, f"{name} leaked Jinja marker {marker!r}"


@pytest.mark.parametrize(
    ("name", "var_name"),
    [
        ("analyze.j2", "task"),
        ("implement.j2", "task"),
        ("review.j2", "criteria"),
        ("summarize.j2", "subject"),
    ],
)
def test_required_var_appears_verbatim(name: str, var_name: str) -> None:
    """The user-supplied required var must reach the rendered prompt unchanged."""
    env = _env()
    rendered = env.get_template(name).render(**REQUIRED_VARS[name])
    assert REQUIRED_VARS[name][var_name] in rendered


# ---------------------------------------------------------------------------
# Rendering — missing required vars → UndefinedError (StrictUndefined)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_raises_when_required_var_missing(name: str) -> None:
    env = _env()
    template = env.get_template(name)
    with pytest.raises(UndefinedError):
        # Render with no vars — the required one is undefined.
        template.render()


# ---------------------------------------------------------------------------
# submit_tool_name — defaults to literal "submit", overridable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", TEMPLATES)
def test_submit_tool_name_defaults_to_submit(name: str) -> None:
    env = _env()
    rendered = env.get_template(name).render(**REQUIRED_VARS[name])
    assert "submit" in rendered, f"{name} does not mention the submit tool"


@pytest.mark.parametrize("name", TEMPLATES)
def test_submit_tool_name_override_appears(name: str) -> None:
    env = _env()
    override = "submit_my_node_42"
    rendered = env.get_template(name).render(
        submit_tool_name=override, **REQUIRED_VARS[name]
    )
    assert override in rendered, f"{name} did not honour submit_tool_name override"


# ---------------------------------------------------------------------------
# Header comment block — present, lists required vars by name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "var_name"),
    [
        ("analyze.j2", "task"),
        ("implement.j2", "task"),
        ("review.j2", "criteria"),
        ("summarize.j2", "subject"),
    ],
)
def test_template_source_has_header_comment_listing_required_var(
    name: str, var_name: str
) -> None:
    """Header `{# ... #}` block must document the required template_var name."""
    source = (PROMPTS_DIR / name).read_text()
    assert source.lstrip().startswith("{#"), f"{name} missing leading {{# ... #}} header"
    # Find the first comment block and check the required var name is mentioned.
    end = source.find("#}")
    assert end > 0, f"{name} header comment never closes"
    header = source[: end + 2]
    assert var_name in header, (
        f"{name} header comment must mention required var {var_name!r}"
    )


# ---------------------------------------------------------------------------
# Optional vars — swap default behaviour
# ---------------------------------------------------------------------------


def test_review_default_severity_levels_in_output() -> None:
    env = _env()
    rendered = env.get_template("review.j2").render(**REQUIRED_VARS["review.j2"])
    assert "HIGH" in rendered
    assert "MEDIUM" in rendered
    assert "LOW" in rendered


def test_review_severity_levels_override_replaces_default_trio() -> None:
    env = _env()
    rendered = env.get_template("review.j2").render(
        severity_levels=["BLOCKING", "ADVISORY"],
        **REQUIRED_VARS["review.j2"],
    )
    assert "BLOCKING" in rendered
    assert "ADVISORY" in rendered
    # Defaults must be gone when overridden.
    assert "HIGH" not in rendered
    assert "MEDIUM" not in rendered
    assert "LOW" not in rendered


def test_analyze_tools_hint_optional_appears_when_supplied() -> None:
    env = _env()
    hint = "Prefer Grep over reading whole files; this codebase is large"
    rendered = env.get_template("analyze.j2").render(
        tools_hint=hint, **REQUIRED_VARS["analyze.j2"]
    )
    assert hint in rendered


def test_analyze_tools_hint_absent_when_omitted() -> None:
    env = _env()
    rendered = env.get_template("analyze.j2").render(**REQUIRED_VARS["analyze.j2"])
    # Sentinel string — it should never leak in when no hint is supplied.
    assert "Prefer Grep over reading whole files" not in rendered


def test_implement_constraints_optional_appears_when_supplied() -> None:
    env = _env()
    constraints = "No new third-party dependencies. Stay within harness/state/."
    rendered = env.get_template("implement.j2").render(
        constraints=constraints, **REQUIRED_VARS["implement.j2"]
    )
    assert constraints in rendered


def test_implement_constraints_absent_when_omitted() -> None:
    env = _env()
    rendered = env.get_template("implement.j2").render(**REQUIRED_VARS["implement.j2"])
    assert "No new third-party dependencies" not in rendered


def test_summarize_length_default_is_concise() -> None:
    env = _env()
    rendered = env.get_template("summarize.j2").render(**REQUIRED_VARS["summarize.j2"])
    assert "concise" in rendered.lower()


def test_summarize_length_override() -> None:
    env = _env()
    rendered = env.get_template("summarize.j2").render(
        length="two paragraphs", **REQUIRED_VARS["summarize.j2"]
    )
    assert "two paragraphs" in rendered
    # Default must be gone when overridden.
    assert "concise" not in rendered.lower()

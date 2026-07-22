"""Tests for ``resolve_model_tier`` — per-ticket model tiering (#177).

AC-1: ``resolve_model_tier(labels, dimension)`` is a pure function returning
``sonnet``/``opus``, defaulting to ``sonnet`` on an absent/unknown label,
independently for the ``build`` and ``review`` dimensions.
"""

from __future__ import annotations

from harness.cli.review_protocol import resolve_model_tier


def test_review_opus_label_resolves_opus() -> None:
    assert resolve_model_tier(["review:opus"], "review") == "opus"


def test_review_sonnet_label_resolves_sonnet() -> None:
    assert resolve_model_tier(["review:sonnet"], "review") == "sonnet"


def test_absent_label_defaults_sonnet() -> None:
    assert resolve_model_tier([], "review") == "sonnet"
    assert resolve_model_tier(["some-other-label"], "review") == "sonnet"


def test_unknown_tier_value_defaults_sonnet() -> None:
    assert resolve_model_tier(["review:ultra"], "review") == "sonnet"


def test_dimensions_are_independent() -> None:
    labels = ["build:opus", "review:sonnet"]
    assert resolve_model_tier(labels, "build") == "opus"
    assert resolve_model_tier(labels, "review") == "sonnet"


def test_build_label_absent_defaults_sonnet_even_with_review_label_present() -> None:
    assert resolve_model_tier(["review:opus"], "build") == "sonnet"


def test_matching_is_case_insensitive() -> None:
    assert resolve_model_tier(["Review:Opus"], "review") == "opus"

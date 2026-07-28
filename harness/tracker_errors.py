"""Tracker-agnostic boundary exceptions — the errors the verbs catch (CAL-1105).

The verbs talk to a :class:`~harness.tracker.Tracker` through the seam, so they
must catch failures without naming a backend. These three base classes are that
vocabulary; each backend's boundary exceptions subclass them
(:class:`~harness.linear.LinearConfigError` ⊂ :class:`TrackerConfigError`,
:class:`~harness.github.GitHubNotFound` ⊂ :class:`TrackerNotFound`, and so on).

They live in their own leaf module — imported by ``linear``, ``github``, and
``tracker`` alike — so no import cycle forms: ``tracker`` imports the backends,
the backends import these, and these import nothing from ``harness``.

Subclassing is deliberately transparent to the existing Linear path: an
``except LinearNotFound`` still catches exactly what it did, and an
``isinstance(exc, LinearNotFound)`` check is unchanged — only a new, wider
``except TrackerNotFound`` additionally catches the GitHub backend's equivalent.
"""

from __future__ import annotations

__all__ = [
    "TrackerConfigError",
    "TrackerNotFound",
    "TrackerRequestError",
    "TrackerTransitionUnconfirmed",
]


class TrackerConfigError(RuntimeError):
    """Required tracker configuration (a credential or a config block) is missing.

    The base of :class:`~harness.linear.LinearConfigError` and
    :class:`~harness.github.GitHubConfigError`. A verb catches this at client
    construction and reports it as an invocation error (exit 2).
    """


class TrackerNotFound(RuntimeError):  # noqa: N818 — SPEC vocab, not PEP 8 Error suffix
    """The requested issue (or its container) does not exist or is inaccessible.

    The base of :class:`~harness.linear.LinearNotFound` and
    :class:`~harness.github.GitHubNotFound`.
    """


class TrackerRequestError(RuntimeError):
    """The tracker API returned an error or an unexpected response.

    The base of :class:`~harness.linear.LinearRequestError` and
    :class:`~harness.github.GitHubRequestError`.
    """


class TrackerTransitionUnconfirmed(TrackerRequestError):  # noqa: N818 — SPEC vocab
    """A transition mutation returned without error, but the tracker's
    post-write state is not the state that was requested (#233).

    Subclasses :class:`TrackerRequestError` — not a fresh ``RuntimeError`` —
    so every verb that already catches that base (``start`` rolls the run
    back, ``review`` warns and keeps the verdict, ``reclaim`` exits 2) handles
    an unconfirmed transition as the tracker failure it already models,
    without a new unhandled path. Only ``close`` branches on the subclass
    itself, to attach its own ``ticket_transition_unconfirmed`` reason.
    """

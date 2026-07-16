"""Canonical run-status vocabulary — see ``specs/features/run-ledger.md``.

This module owns :data:`RunStatus` / :data:`RUN_STATUSES`, the type-safe seam
writers and CLI readers share for the ``runs.status`` string.

It once also carried ``BaseState``, the engine-era pydantic model of the
run-state shape. CAL-574 retired the workflow engine, leaving that model with no
production importer; CAL-1107 deleted it. The persisted run shape now lives in
the ``runs`` table schema (``harness.state.store``), and no model validates the
(always-empty) ``state_json`` blob.
"""

from __future__ import annotations

from typing import Literal, get_args

__all__ = ["RUN_STATUSES", "RunStatus"]


# Canonical run-status enum — see ``specs/features/run-ledger.md`` ("status values").
# The SQLite column is ``TEXT NOT
# NULL`` without a CHECK constraint, so this Literal is the type-safe seam:
# writers + CLI readers import :data:`RUN_STATUSES` to validate the string
# they read out of the DB.
#
# Two lifecycles are folded into one set:
#
# * Verb model (current) — ``harness start`` opens a run as ``open`` and
#   ``harness close`` finalizes it to ``closed`` (CAL-583). These are the
#   statuses live code writes today.
# * Retired deterministic engine — ``pending``/``running``/``completed``/
#   ``failed``/``cancelled``/``stalled``/``paused`` were the per-node engine
#   states (``paused``/``stalled`` were the v1.5/H-025 lifecycle additions).
#   CAL-574 retired the engine; these are kept so historical rows still
#   validate (removing them is out of scope).
RunStatus = Literal[
    # verb model
    "open",
    "closed",
    # retired deterministic engine
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "stalled",
    "paused",
]

RUN_STATUSES: frozenset[str] = frozenset(get_args(RunStatus))
"""Runtime view of the canonical run statuses — derived from
:data:`RunStatus` so the two cannot drift."""

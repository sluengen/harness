"""Paused-state persistence — H-2-002 / H-2-005.

The pause machinery shipped in H-2-002 lives in
:meth:`harness.engine.runner.Runner._finalise_pause`. That method:

1. Updates ``runs.status`` to ``'paused'`` and ``exit_code`` to ``4``.
2. Emits ``decision_requested`` with ``step_id`` and ``message``.
3. Emits ``workflow_paused`` with ``step_id``.
4. Prints the decision message and resume instructions to stdout.

The ``run_snapshots`` table (H-2-001) provides the snapshot history
that the companion :mod:`harness.decisions.resume` module reads on
resume.
"""

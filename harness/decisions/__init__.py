"""Human-decision resume machinery — H-2-002 / H-2-005.

Public surface:
  :func:`~harness.decisions.resume.rehydrate_state`  — snapshot-based
      state rehydration for paused runs.
"""

from harness.decisions.resume import rehydrate_state

__all__ = ["rehydrate_state"]

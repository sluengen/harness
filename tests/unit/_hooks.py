"""Captured host payloads the hook guards read.

A payload observed from a real host is evidence, not a fixture: it is the one
thing in a hook's test module that is not a model of the contract. That makes it
the wrong thing to keep in a ``test_*.py`` module, because a second guard needing
it turns that module into a library — the coupling #467 removed everywhere else
in this suite.

It lives here rather than in :mod:`tests.unit._prose`, which reads prose out of
the tree and has nothing to do with host contracts.
"""

from __future__ import annotations

#: The **verbatim** Stop payload a real host sent, captured live from Claude Code
#: 2.1.220 by a snapshot hook that copied its stdin at the instant the Stop hook
#: ran. Every key here was observed; none was modelled — which is the whole point
#: of it, because §12.5 of the design says the rest of the Stop-hook fixtures are
#: models of the host's contract and self-consistent whether or not they are
#: right. This one is the contract.
#:
#: The load-bearing observation is what is *not* in it: the same snapshot counted
#: **zero assistant entries in the transcript** at Stop time. The host appends the
#: turn's assistant message to the JSONL only *after* the Stop hook returns, so a
#: hook that reads its trigger out of the transcript reads a file that does not
#: yet contain the turn being stopped, and can never fire. The message is handed
#: over directly instead, as the top-level ``last_assistant_message``.
#: The two path fields are **redacted**, and they are the only two: they named
#: the capturing operator's home directory, which ``test_no_private_surfaces``
#: rightly refuses in a tracked file. Nothing is lost by it — every test rebinds
#: both to its own tmp_path anyway, because the captured directories do not exist
#: here. Every other key is byte-for-byte what the host sent.
REAL_STOP_PAYLOAD: dict[str, object] = {
    "session_id": "3321d2eb-025e-4025-9770-989edb1dffe9",
    "transcript_path": "~/.claude/projects/<redacted>/3321d2eb-025e-4025-9770-989edb1dffe9.jsonl",
    "cwd": "<redacted>/scratchpad/stopprobe",
    "prompt_id": "b9b30132-647a-42a6-9271-1f4231bafcd3",
    "permission_mode": "default",
    "effort": {"level": "high"},
    "hook_event_name": "Stop",
    "stop_hook_active": False,
    "last_assistant_message": "Done — the implementation is complete and all tests pass.",
    "background_tasks": [],
    "session_crons": [],
}

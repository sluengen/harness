"""Read a ``claude --output-format stream-json`` transcript (#361).

A **test helper, never production code.** Nothing in ``harness/`` parses
stream-json: the production ``review`` invocation is
``claude -p --permission-mode plan`` and the verb scans stdout for one
``SUBMIT:`` line. This module exists only so a test can answer the question the
visual-evidence channel rests on — *did the engine's tool result come back as
image content, or as text about an image?* — and it is deliberately not wired
into any verb (see the rejected alternative in #361's design: parsing
stream-json in production would change the ``SUBMIT``-line contract for both
engines and both verbs).

Two consumers, one function, on purpose (the repo's shape for a non-vacuous
oracle): ``tests/unit/test_stream_json_oracle.py`` proves it against synthetic
positive and negative streams, and
``tests/integration/test_review_visual_live.py`` asserts through it against a
real engine run. A separate reader in either place would let the live assertion
pass on a predicate nothing had proven.
"""

from __future__ import annotations

import json
from typing import Any


def _content_blocks(event: object) -> list[Any]:
    """The ``message.content`` list of one stream event, or empty."""
    if not isinstance(event, dict):
        return []
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    return content if isinstance(content, list) else []


def _is_image_result(block: dict[str, Any]) -> bool:
    """Whether a ``tool_result`` block carries an ``image`` **content block**.

    The discrimination this whole module exists for. A tool result whose content
    is text — the path echoed back, a base64 blob, or a sentence about an image —
    is not an image content block, however much it talks about one.
    """
    inner = block.get("content")
    if not isinstance(inner, list):
        return False
    return any(isinstance(b, dict) and b.get("type") == "image" for b in inner)


def image_tool_result_paths(stream: str) -> tuple[str, ...]:
    """The ``file_path`` of every ``Read`` whose tool result was image content.

    ``stream`` is the raw stdout of ``claude --output-format stream-json
    --verbose``: one JSON object per line. Unparseable lines are skipped, so a
    transcript truncated mid-write still reports what it did contain.

    Correlation is by ``tool_use_id``, not by position: a run that reads several
    files gets one result per read, and only the reads whose *own* result carried
    an image are returned — in the order the reads were issued.
    """
    reads: dict[str, str] = {}
    image_ids: set[str] = set()
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for block in _content_blocks(event):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Read":
                tool_id = block.get("id")
                raw_input = block.get("input")
                path = raw_input.get("file_path") if isinstance(raw_input, dict) else None
                if isinstance(tool_id, str) and isinstance(path, str):
                    reads[tool_id] = path
            elif block.get("type") == "tool_result" and _is_image_result(block):
                tool_id = block.get("tool_use_id")
                if isinstance(tool_id, str):
                    image_ids.add(tool_id)
    return tuple(path for tool_id, path in reads.items() if tool_id in image_ids)

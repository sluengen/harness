"""T1 (#361) — the stream-json oracle, proven positive **and** negative.

:func:`tests._stream_json.image_tool_result_paths` is the instrument AC-1b rests
on: it answers *which files the engine read back as image content*, as opposed to
merely mentioning, echoing, or base64-dumping. The live test
(``tests/integration/test_review_visual_live.py``) asserts through it, and a live
test is skipped in the gate — so the oracle itself has to be proven here, on
synthetic streams, or the one assertion that makes AC-1b mean anything rests on
an unverified reader.

The negative cases are the point. A reader relaxed to ``"image" in
json.dumps(block)`` satisfies the positive case *and* the two obvious negatives
(a path echoed as text, a base64 blob) — case (d), a text result that merely
contains the word "image", is the one that kills it. It is not decoration.
"""

from __future__ import annotations

import json
from typing import Any

from tests._stream_json import image_tool_result_paths


def _read_use(tool_id: str, path: str) -> dict[str, Any]:
    """One ``Read`` tool_use block, as the claude CLI streams it."""
    return {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "Read",
                    "input": {"file_path": path},
                }
            ]
        },
    }


def _result(tool_id: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    """The matching ``tool_result``, carrying whatever content blocks it got."""
    return {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": content,
                }
            ]
        },
    }


def _stream(*events: dict[str, Any]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


_IMAGE_BLOCK = {
    "type": "image",
    "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="},
}


def test_a_read_whose_result_is_an_image_block_is_returned() -> None:
    """(a) The positive case — the mechanism AC-1b claims."""
    stream = _stream(
        _read_use("toolu_a", "/workspace/shots/full-1440.png"),
        _result("toolu_a", [_IMAGE_BLOCK]),
    )

    assert image_tool_result_paths(stream) == ("/workspace/shots/full-1440.png",)


def test_a_text_result_that_is_the_path_itself_is_not_returned() -> None:
    """(b) The engine echoing the path back is *not* the engine seeing pixels."""
    stream = _stream(
        _read_use("toolu_b", "/workspace/shots/full-1440.png"),
        _result("toolu_b", [{"type": "text", "text": "/workspace/shots/full-1440.png"}]),
    )

    assert image_tool_result_paths(stream) == ()


def test_a_text_result_carrying_a_base64_blob_is_not_returned() -> None:
    """(c) Bytes-as-text is the degraded shape the channel must not read as success."""
    stream = _stream(
        _read_use("toolu_c", "/workspace/shots/full-1440.png"),
        _result(
            "toolu_c",
            [{"type": "text", "text": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"}],
        ),
    )

    assert image_tool_result_paths(stream) == ()


def test_a_text_result_merely_mentioning_an_image_is_not_returned() -> None:
    """(d) **The exclusive killer.** Do not delete this case.

    A reader relaxed to ``"image" in json.dumps(block)`` — the laziest
    implementation that still passes (a), (b) and (c) — returns the path here.
    The discrimination the oracle claims is between an ``image`` *content block*
    and text about an image, and only this case measures it.
    """
    stream = _stream(
        _read_use("toolu_d", "/workspace/shots/full-1440.png"),
        _result(
            "toolu_d",
            [{"type": "text", "text": "This file is an image; I cannot display it."}],
        ),
    )

    assert image_tool_result_paths(stream) == ()


def test_only_the_read_that_came_back_as_an_image_is_returned() -> None:
    """Two reads, one image — kills a fixed sentinel and a return-every-read reader.

    (a) alone is satisfied by an oracle that returns the path of every ``Read``
    it sees, or of the first one. With two reads whose results differ, only a
    reader that correlates each ``tool_use_id`` with its own result survives.
    """
    stream = _stream(
        _read_use("toolu_1", "/workspace/shots/a.png"),
        _read_use("toolu_2", "/workspace/shots/b.png"),
        _result("toolu_1", [{"type": "text", "text": "a text rendering"}]),
        _result("toolu_2", [_IMAGE_BLOCK]),
    )

    assert image_tool_result_paths(stream) == ("/workspace/shots/b.png",)


def test_unparseable_and_unrelated_lines_are_skipped() -> None:
    """A real stream carries init/result lines and can be truncated mid-write."""
    stream = (
        '{"type":"system","subtype":"init","session_id":"x"}\n'
        + _stream(
            _read_use("toolu_e", "/workspace/shots/a.png"),
            _result("toolu_e", [_IMAGE_BLOCK]),
        )
        + '{"type":"result","subtype":"suc'
    )

    assert image_tool_result_paths(stream) == ("/workspace/shots/a.png",)

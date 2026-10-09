"""#756, #763 — ``scripts/landing-window.js``: may this train land now.

ADR 0024 gives the landing train every interval between departures, on the grid
of fires an optional ``cadence:`` block in ``harness.yaml`` declares. This script
is the one place that arithmetic lives, so two runs reading the same clock cannot
disagree about whether a train's window is open, and no skill re-derives one in
prose. ADR 0023's routine windows and attended reserve are retired (#763), and so
are the runs that asked for them.

What is measured here, and why each matters:

* **No block lands as today.** A consumer without ``cadence:`` must see exit 0,
  ``case: "no-cadence"`` (AC-2 of #756).
* **A train's window runs from its slot to the next grid fire (#762).** Its slot
  is the latest fire at or before its departure, so a late start keeps its slot,
  and it closes at the grid's next real fire, so a daylight-saving gap lengthens
  it rather than closing it early.
* **The grid lives in a declared zone.** Fires are the anchor's wall times every
  pitch minutes in ``timezone``. A spring-forward gap does not fire and a
  fall-back repeat fires at its earlier occurrence; the Sydney cases fail both a
  naive UTC grid and a fixed-offset one.
* **The block is the timetable, three keys (#763).** ``timezone``, ``anchor`` and
  ``pitch`` validate on their own, and a block declared under ADR 0023 still
  lands a train whatever its retired keys say, because nothing reads them.
* **The retired runs are usage errors (#763).** ``--run routine`` and ``--run
  attended`` exit 64 with nothing on stdout.
* **Malformed is never absent.** An unreadable block refuses with exit 2 rather
  than falling through to ``no-cadence``, and an invalid one refuses naming its
  key.

**Why a second fixture with other numbers.** Every base value appears in the
base fixture, so a script that hardcoded them would pass every base case. The
second fixture pins the derivation rather than the derived answer (#458).

These read fixture working trees, which is right for a script whose operand is
the checkout it is pointed at; the index rule in ``.claude/rules/scripts.md``
governs guards over what ships, and this is not one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "landing-window.js"

#: The template's timetable, on a UTC grid so the base cases read in plain
#: minutes. The order is the template's.
BASE: dict[str, str] = {
    "timezone": "UTC",
    "anchor": '"00:57"',
    "pitch": "120",
}

#: The five keys ADR 0023 declared beside the timetable, with its template's
#: values. ADR 0024 retired what read them (#763).
RETIRED: dict[str, str] = {
    "attended.open": "15",
    "attended.close": "45",
    "routine.open": "45",
    "routine.close": "135",
    "parked_limit": "1",
}

#: A scheduled fire on the base grid. Every base case is an offset from it.
T = datetime(2026, 10, 7, 10, 57, tzinfo=UTC)


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _block(values: dict[str, str | None]) -> str:
    """A ``cadence:`` block; a ``None`` value leaves that key out."""
    lines = ["cadence:"]
    lines += [f"  {key}: {value}" for key, value in values.items() if value is not None]
    return "\n".join(lines) + "\n"


def _cadence(**overrides: str | None) -> str:
    """The base block with ``overrides`` applied. Dotted keys are spelled with
    ``__`` in the keyword, since a Python identifier cannot carry a dot."""
    values: dict[str, str | None] = dict(BASE)
    for key, value in overrides.items():
        values[key.replace("__", ".")] = value
    return _block(values)


def _repo(tmp_path: Path, config: str | None, name: str = "repo") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--initial-branch=dev"], cwd=root, check=True)
    text = "repo:\n  name: fixture\n"
    if config is not None:
        (root / "harness.yaml").write_text(text + config, newline="")
    return root


def _run(cwd: Path, *args: str) -> tuple[int, dict[str, object], str, str]:
    """Spawn the production script: ``(exit, payload, stdout, stderr)``."""
    proc = subprocess.run(
        [_node(), str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload: dict[str, object] = {}
    if proc.stdout.strip():
        payload = json.loads(proc.stdout)
    return proc.returncode, payload, proc.stdout, proc.stderr


def _z(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(moment: datetime) -> str:
    """How the script renders an instant on a UTC grid."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _at(minutes: float) -> datetime:
    return T + timedelta(minutes=minutes)


def _train(repo: Path, fired: datetime, now: datetime) -> tuple[int, dict[str, object]]:
    code, payload, _, err = _run(repo, "--run", "train", "--fired", _z(fired), "--now", _z(now))
    assert code in (0, 1, 2), f"exit {code}: {err}"
    return code, payload


# --- no block lands as today -------------------------------------------------


@pytest.mark.parametrize("config", [None, ""], ids=["no-harness-yaml", "no-cadence-block"])
def test_no_cadence_lands_as_today(tmp_path: Path, config: str | None) -> None:
    repo = _repo(tmp_path, config)
    code, payload, _, err = _run(repo, "--run", "train", "--fired", _z(T), "--now", _z(_at(50)))
    assert (code, payload.get("case"), payload.get("run")) == (0, "no-cadence", "train"), err


# --- AC-2a (#762): the train's window, from its slot to the next fire ---------


def test_a_train_inside_its_window_may_land(tmp_path: Path) -> None:
    """The whole payload, key order included: no ``opens``, which is ``fired``,
    and no ``parked_limit``, which #763 retired."""
    repo = _repo(tmp_path, _cadence())
    code, payload = _train(repo, T, _at(50))
    assert code == 0
    assert payload == {
        "case": "open",
        "run": "train",
        "now": _utc(_at(50)),
        "fired": _utc(T),
        "closes": _utc(_at(120)),
    }
    assert list(payload) == ["case", "run", "now", "fired", "closes"]


def test_a_train_that_started_late_keeps_its_scheduled_slot(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence())
    code, payload = _train(repo, _at(40), _at(50))
    assert (code, payload.get("case")) == (0, "open")
    assert (payload.get("fired"), payload.get("closes")) == (_utc(T), _utc(_at(120)))


@pytest.mark.parametrize(
    ("now", "code", "case"),
    [(_at(119) + timedelta(seconds=59), 0, "open"), (_at(120), 1, "closed")],
    ids=["a-second-before-the-next-fire", "at-the-next-fire"],
)
def test_a_train_window_is_half_open(tmp_path: Path, now: datetime, code: int, case: str) -> None:
    repo = _repo(tmp_path, _cadence())
    got, payload = _train(repo, T, now)
    assert (got, payload.get("case")) == (code, case)


def test_a_closed_train_names_its_own_close(tmp_path: Path) -> None:
    """A closed train names its own close, never a later train's: nothing it
    could wait for is its window."""
    repo = _repo(tmp_path, _cadence())
    code, payload = _train(repo, T, _at(130))
    assert (code, payload.get("case")) == (1, "closed")
    assert (payload.get("fired"), payload.get("closes")) == (_utc(T), _utc(_at(120)))


def test_other_numbers_give_other_train_windows(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence(anchor='"03:30"', pitch="240"))
    fire = datetime(2026, 10, 7, 11, 30, tzinfo=UTC)
    code, payload = _train(repo, fire + timedelta(minutes=15), fire + timedelta(minutes=60))
    assert (code, payload.get("case")) == (0, "open")
    assert (payload.get("fired"), payload.get("closes")) == (
        _utc(fire),
        _utc(fire + timedelta(minutes=240)),
    )


def test_a_train_started_a_second_before_the_next_fire_keeps_its_slot(
    tmp_path: Path,
) -> None:
    """Flooring, not rounding: a departure a second before the next fire belongs
    to the slot before it, so by T+121 its window has closed."""
    repo = _repo(tmp_path, _cadence())
    code, payload = _train(repo, _at(119) + timedelta(seconds=59), _at(121))
    assert (code, payload.get("case")) == (1, "closed")
    assert payload.get("fired") == _utc(T)


def test_a_train_window_runs_past_midnight(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence())
    fired = datetime(2026, 10, 7, 22, 57, tzinfo=UTC)
    code, payload = _train(repo, fired, datetime(2026, 10, 7, 23, 59, tzinfo=UTC))
    assert (code, payload.get("case")) == (0, "open")
    assert (payload.get("fired"), payload.get("closes")) == (
        _utc(fired),
        "2026-10-08T00:57:00+00:00",
    )


@pytest.mark.parametrize("minutes", [20, 60, 125, 140])
def test_the_anchor_is_a_member_of_the_grid_not_its_origin(tmp_path: Path, minutes: int) -> None:
    first = _repo(tmp_path, _cadence(anchor='"00:57"'), "first")
    other = _repo(tmp_path, _cadence(anchor='"10:57"'), "other")
    answers = (_train(first, T, _at(minutes)), _train(other, T, _at(minutes)))
    # Two crashes compare equal, so the answer must be one first.
    assert answers[0][1].get("case") in {"open", "closed"}, answers[0]
    assert answers[0] == answers[1]


# --- #763: the block is the timetable ----------------------------------------


def test_a_block_declared_under_adr_0023_still_lands_a_train(tmp_path: Path) -> None:
    """Nothing reads the retired keys, so not even a value ADR 0023 refused can
    refuse: a negative ``parked_limit`` leaves the train's answer untouched."""
    repo = _repo(tmp_path, _block({**BASE, **RETIRED, "parked_limit": "-1"}))
    code, payload = _train(repo, T, _at(50))
    assert (code, payload.get("case"), payload.get("closes")) == (0, "open", _utc(_at(120)))


# --- AC-1: daylight saving in Australia/Sydney -------------------------------
#
# 2026-10-04 02:00 AEST (+10) becomes 03:00 AEDT (+11), at 16:00Z on the 3rd.
# On the even-hour :57 grid, 00:57 AEST fires at 14:57Z, 02:57 does not exist,
# and 04:57 AEDT fires at 17:57Z. A naive +120-minute UTC grid would fire at
# 16:57Z and put the next reserve at 17:12Z.

SYDNEY = _cadence(timezone="Australia/Sydney")


def test_a_train_window_runs_to_the_next_real_fire_across_spring_forward(
    tmp_path: Path,
) -> None:
    """The train that departs at 00:57 AEST has no 02:57 successor, so its window
    runs to 04:57 AEDT (17:57Z). Slot plus pitch would close it at 16:57Z."""
    repo = _repo(tmp_path, SYDNEY)
    fired = datetime(2026, 10, 3, 14, 57, tzinfo=UTC)
    code, payload = _train(repo, fired, datetime(2026, 10, 3, 17, 0, tzinfo=UTC))
    assert (code, payload.get("case")) == (0, "open")
    assert (payload.get("fired"), payload.get("closes")) == (
        "2026-10-04T00:57:00+10:00",
        "2026-10-04T04:57:00+11:00",
    )
    code, payload = _train(repo, fired, datetime(2026, 10, 3, 17, 57, tzinfo=UTC))
    assert (code, payload.get("case")) == (1, "closed")


def test_a_train_at_the_repeated_fall_back_fire_floors_to_the_earlier(tmp_path: Path) -> None:
    """02:57 fires once, at 15:57Z; a train started at the repeat (16:57Z) is that
    train, and its window runs to 04:57 AEST (18:57Z)."""
    repo = _repo(tmp_path, SYDNEY)
    fired = datetime(2027, 4, 3, 16, 57, tzinfo=UTC)
    code, payload = _train(repo, fired, datetime(2027, 4, 3, 18, 30, tzinfo=UTC))
    assert (code, payload.get("case")) == (0, "open")
    assert (payload.get("fired"), payload.get("closes")) == (
        "2027-04-04T02:57:00+11:00",
        "2027-04-04T04:57:00+10:00",
    )


# --- unreadable is never absent ----------------------------------------------


@pytest.mark.parametrize(
    "config",
    [
        "cadence: {timezone: UTC, pitch: 120\n",
        "cadence:\n  timezone: UTC\n  routine:\n    open: 45\n",
        "cadence:\nother: x\n",
    ],
    ids=["unclosed-flow", "nested-sub-block", "empty-block"],
)
def test_an_unreadable_block_refuses(tmp_path: Path, config: str) -> None:
    repo = _repo(tmp_path, config)
    code, payload, _, err = _run(repo, "--run", "train", "--fired", _z(T), "--now", _z(_at(50)))
    assert (code, payload.get("case")) == (2, "unreadable-cadence"), err
    assert payload.get("sources") == ["harness.yaml"]


# --- invalid values refuse, naming the key -----------------------------------


INVALID: dict[str, tuple[dict[str, str | None], str]] = {
    **{f"missing-{key}": ({key.replace(".", "__"): None}, key) for key in BASE},
    "pitch-not-dividing-a-day": ({"pitch": "100"}, "pitch"),
    "pitch-zero": ({"pitch": "0"}, "pitch"),
    "anchor-hour-24": ({"anchor": '"24:00"'}, "anchor"),
    "anchor-not-a-time": ({"anchor": "noon"}, "anchor"),
    "pitch-with-a-unit": ({"pitch": "120m"}, "pitch"),
    "pitch-fractional": ({"pitch": "1.5"}, "pitch"),
    "unknown-zone": ({"timezone": "Mars/Olympus"}, "timezone"),
}


@pytest.mark.parametrize("name", sorted(INVALID))
def test_an_invalid_block_refuses_naming_the_key(tmp_path: Path, name: str) -> None:
    overrides, key = INVALID[name]
    repo = _repo(tmp_path, _cadence(**overrides))
    code, payload, _, err = _run(repo, "--run", "train", "--fired", _z(T), "--now", _z(_at(50)))
    assert (code, payload.get("case"), payload.get("key")) == (2, "invalid-cadence", key), err
    assert payload.get("reason")


# --- usage --------------------------------------------------------------------


USAGE: dict[str, list[str]] = {
    "no-run": ["--now", "2026-10-07T11:47:00Z"],
    "unknown-run": ["--run", "nightly", "--now", "2026-10-07T11:47:00Z"],
    "train-without-fired": ["--run", "train", "--now", "2026-10-07T11:47:00Z"],
    "train-fired-after-now": [
        "--run", "train", "--fired", "2026-10-07T12:00:00Z", "--now", "2026-10-07T11:47:00Z"
    ],
    "now-without-offset": [
        "--run", "train", "--fired", "2026-10-07T10:57:00Z", "--now", "2026-10-07T11:47:00"
    ],
    "unknown-flag": [
        "--run", "train", "--fired", "2026-10-07T10:57:00Z", "--when", "2026-10-07T11:47:00Z"
    ],
    # Well-formed but for the run name, which ADR 0024 retired (#763).
    "retired-run-routine": [
        "--run", "routine", "--fired", "2026-10-07T10:57:00Z", "--now", "2026-10-07T11:47:00Z"
    ],
    "retired-run-attended": ["--run", "attended", "--now", "2026-10-07T11:47:00Z"],
}


@pytest.mark.parametrize("name", sorted(USAGE))
def test_usage_errors_exit_64_with_nothing_on_stdout(tmp_path: Path, name: str) -> None:
    repo = _repo(tmp_path, _cadence())
    code, _, out, err = _run(repo, *USAGE[name])
    assert (code, out) == (64, ""), err
    assert err.strip()


# --- the source, and the root -------------------------------------------------


@pytest.mark.parametrize(
    "harness_yaml", [None, ""], ids=["no-harness-yaml", "harness-yaml-without"]
)
def test_a_cadence_fenced_in_a_spine_is_not_read(tmp_path: Path, harness_yaml: str | None) -> None:
    repo = _repo(tmp_path, harness_yaml)
    (repo / "AGENTS.md").write_text("# Spine\n\n```yaml\n" + _cadence() + "```\n")
    code, payload, _, err = _run(repo, "--run", "train", "--fired", _z(T), "--now", _z(_at(60)))
    assert (code, payload.get("case")) == (0, "no-cadence"), err


def test_repo_names_a_subdirectory_of_the_checkout(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence())
    (repo / "sub").mkdir()
    code, payload, _, err = _run(
        tmp_path, "--repo", str(repo / "sub"), "--run", "train", "--fired", _z(T),
        "--now", _z(_at(130)),
    )
    assert (code, payload.get("case")) == (1, "closed"), err


def test_a_directory_outside_any_checkout_refuses(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    code, payload, _, err = _run(plain, "--run", "train", "--fired", _z(T), "--now", _z(_at(60)))
    assert (code, payload.get("case")) == (2, "not-a-work-tree"), err

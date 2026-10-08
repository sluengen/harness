"""#756 — ``scripts/landing-window.js``: may this run land now, and when.

ADR 0023 gives each scheduled tick a routine landing window and attended work a
reserve, both derived from the clock and an optional ``cadence:`` block in
``harness.yaml``. This script is the one place that arithmetic lives, so two
runs reading the same clock cannot disagree about whose window is open, and no
skill re-derives a window in prose.

What is measured here, and why each matters:

* **No block lands as today.** A consumer without ``cadence:`` must see exit 0,
  ``case: "no-cadence"``, from either run kind (AC-2).
* **A routine's own window is found from its fired instant, not the clock.**
  The window of the tick that fired at T runs 15 minutes into the next pitch, so
  at T+125 the T tick is ``open`` and the T+120 tick is ``not-yet``; only the
  ``--fired`` instant tells them apart (AC-1).
* **The grid lives in a declared zone.** Fires are the anchor's wall times every
  pitch minutes in ``timezone``. A spring-forward gap does not fire and a
  fall-back repeat fires at its earlier occurrence; the Sydney cases fail both a
  naive UTC grid and a fixed-offset one (AC-1).
* **A train's window runs from its slot to the next grid fire (#762).** ADR 0024
  gives the train every interval between departures. Its slot is found from its
  departure as a routine's is, and it closes at the grid's next real fire, so a
  daylight-saving gap lengthens it rather than closing it early (AC-2a).
* **Malformed is never absent.** An unreadable block refuses with exit 2 rather
  than falling through to ``no-cadence`` (AC-4), and an invalid one refuses
  naming its key (AC-5).

**Why a second fixture with other numbers.** Every calibrate value appears in the
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

#: Calibrate's values from the proposal's *Window placement*, on a UTC grid so
#: the base cases read in plain minutes. The order is the template's.
BASE: dict[str, str] = {
    "timezone": "UTC",
    "anchor": '"00:57"',
    "pitch": "120",
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


def _routine(repo: Path, fired: datetime, now: datetime) -> tuple[int, dict[str, object]]:
    code, payload, _, err = _run(repo, "--run", "routine", "--fired", _z(fired), "--now", _z(now))
    assert code in (0, 1, 2), f"exit {code}: {err}"
    return code, payload


def _train(repo: Path, fired: datetime, now: datetime) -> tuple[int, dict[str, object]]:
    code, payload, _, err = _run(repo, "--run", "train", "--fired", _z(fired), "--now", _z(now))
    assert code in (0, 1, 2), f"exit {code}: {err}"
    return code, payload


def _attended(repo: Path, now: datetime) -> tuple[int, dict[str, object]]:
    code, payload, _, err = _run(repo, "--run", "attended", "--now", _z(now))
    assert code in (0, 1, 2), f"exit {code}: {err}"
    return code, payload


# --- AC-2: no block lands as today -------------------------------------------


@pytest.mark.parametrize("config", [None, ""], ids=["no-harness-yaml", "no-cadence-block"])
@pytest.mark.parametrize("run", ["routine", "attended", "train"])
def test_no_cadence_lands_as_today(tmp_path: Path, config: str | None, run: str) -> None:
    repo = _repo(tmp_path, config)
    args = ["--run", run, "--now", _z(_at(50))]
    if run != "attended":
        args += ["--fired", _z(T)]
    code, payload, _, err = _run(repo, *args)
    assert (code, payload.get("case"), payload.get("run")) == (0, "no-cadence", run), err


# --- AC-1: a routine's own window --------------------------------------------


def test_a_routine_inside_its_window_may_land(tmp_path: Path) -> None:
    """The whole payload, key order included, so the shape is pinned once."""
    repo = _repo(tmp_path, _cadence())
    code, payload = _routine(repo, T, _at(50))
    assert code == 0
    assert payload == {
        "case": "open",
        "run": "routine",
        "now": _utc(_at(50)),
        "fired": _utc(T),
        "opens": _utc(_at(45)),
        "closes": _utc(_at(135)),
        "parked_limit": 1,
    }
    assert list(payload) == ["case", "run", "now", "fired", "opens", "closes", "parked_limit"]


def test_a_routine_past_its_window_is_closed_and_names_the_next_tick(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence())
    code, payload = _routine(repo, T, _at(140))
    assert (code, payload.get("case")) == (1, "closed")
    assert payload.get("fired") == _utc(T)
    # The next routine window is the next tick's +45: informational, it parks.
    assert (payload.get("opens"), payload.get("closes")) == (_utc(_at(165)), _utc(_at(255)))


def test_the_tick_that_fired_at_t_still_owns_its_window_at_t_plus_125(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence())
    code, payload = _routine(repo, T, _at(125))
    assert (code, payload.get("case"), payload.get("closes")) == (0, "open", _utc(_at(135)))


def test_the_next_tick_asking_at_the_same_moment_is_not_yet(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence())
    code, payload = _routine(repo, _at(120), _at(125))
    assert (code, payload.get("case")) == (1, "not-yet")
    assert payload.get("fired") == _utc(_at(120))
    assert (payload.get("opens"), payload.get("closes")) == (_utc(_at(165)), _utc(_at(255)))


@pytest.mark.parametrize(
    ("fired", "now"),
    [(_at(40), _at(50)), (_at(119) + timedelta(seconds=59), _at(121))],
    ids=["started-late", "one-second-before-the-next-fire"],
)
def test_a_routine_is_matched_to_the_latest_fire_at_or_before_it(
    tmp_path: Path, fired: datetime, now: datetime
) -> None:
    repo = _repo(tmp_path, _cadence())
    _, payload = _routine(repo, fired, now)
    assert payload.get("fired") == _utc(T)


@pytest.mark.parametrize(
    ("minutes", "code", "case"),
    [(45, 0, "open"), (135, 1, "closed")],
    ids=["opens-is-inside", "closes-is-outside"],
)
def test_a_window_is_half_open(tmp_path: Path, minutes: int, code: int, case: str) -> None:
    repo = _repo(tmp_path, _cadence())
    got, payload = _routine(repo, T, _at(minutes))
    assert (got, payload.get("case")) == (code, case)


# --- AC-1: the attended reserve ----------------------------------------------


def test_an_attended_run_inside_the_reserve_may_land(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence())
    code, payload = _attended(repo, _at(20))
    assert code == 0
    assert payload == {
        "case": "open",
        "run": "attended",
        "now": _utc(_at(20)),
        "opens": _utc(_at(15)),
        "closes": _utc(_at(45)),
        # The previous tick's routine window closed at T+15.
        "routine_window": None,
        "parked_limit": 1,
    }
    assert list(payload) == [
        "case", "run", "now", "opens", "closes", "routine_window", "parked_limit"
    ]


def test_an_attended_run_outside_the_reserve_names_the_next_and_the_open_routine(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path, _cadence())
    code, payload = _attended(repo, _at(60))
    assert (code, payload.get("case")) == (1, "not-yet")
    assert (payload.get("opens"), payload.get("closes")) == (_utc(_at(135)), _utc(_at(165)))
    assert payload.get("routine_window") == {"opens": _utc(_at(45)), "closes": _utc(_at(135))}


def test_the_next_reserve_wraps_past_midnight(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence())
    now = datetime(2026, 10, 7, 23, 59, tzinfo=UTC)
    code, payload = _attended(repo, now)
    assert (code, payload.get("case")) == (1, "not-yet")
    nxt = datetime(2026, 10, 8, 1, 12, tzinfo=UTC)
    assert (payload.get("opens"), payload.get("closes")) == (
        _utc(nxt),
        _utc(nxt + timedelta(minutes=30)),
    )


@pytest.mark.parametrize("run", ["routine", "attended"])
@pytest.mark.parametrize("minutes", [20, 60, 125, 140])
def test_the_anchor_is_a_member_of_the_grid_not_its_origin(
    tmp_path: Path, run: str, minutes: int
) -> None:
    first = _repo(tmp_path, _cadence(anchor='"00:57"'), "first")
    other = _repo(tmp_path, _cadence(anchor='"10:57"'), "other")
    if run == "routine":
        answers = (_routine(first, T, _at(minutes)), _routine(other, T, _at(minutes)))
    else:
        answers = (_attended(first, _at(minutes)), _attended(other, _at(minutes)))
    # Two crashes compare equal, so the answer must be one first.
    assert answers[0][1].get("case") in {"open", "not-yet", "closed"}, answers[0]
    assert answers[0] == answers[1]


# --- AC-2a (#762): the train's window, from its slot to the next fire ---------


def test_a_train_inside_its_window_may_land(tmp_path: Path) -> None:
    """The whole payload, key order included: no ``opens``, which is ``fired``,
    and no ``parked_limit``, which #763 retires."""
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
    """A routine past its window names the next tick's; a train names its own,
    because nothing it could wait for is its window."""
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


# --- AC-1: the derivation, not calibrate's constants -------------------------


def test_other_numbers_give_other_windows(tmp_path: Path) -> None:
    config = _cadence(
        anchor='"03:30"',
        pitch="240",
        attended__open="10",
        attended__close="50",
        routine__open="60",
        routine__close="200",
        parked_limit="3",
    )
    repo = _repo(tmp_path, config)
    fire = datetime(2026, 10, 7, 11, 30, tzinfo=UTC)

    code, payload = _routine(repo, fire + timedelta(minutes=15), fire + timedelta(minutes=70))
    assert (code, payload.get("case"), payload.get("fired")) == (0, "open", _utc(fire))
    assert (payload.get("opens"), payload.get("closes")) == (
        _utc(fire + timedelta(minutes=60)),
        _utc(fire + timedelta(minutes=200)),
    )
    assert payload.get("parked_limit") == 3

    later = fire + timedelta(minutes=240)
    code, payload = _attended(repo, later + timedelta(minutes=5))
    assert (code, payload.get("case")) == (1, "not-yet")
    assert (payload.get("opens"), payload.get("closes")) == (
        _utc(later + timedelta(minutes=10)),
        _utc(later + timedelta(minutes=50)),
    )
    assert payload.get("routine_window") is None
    assert payload.get("parked_limit") == 3


# --- AC-1: daylight saving in Australia/Sydney -------------------------------
#
# 2026-10-04 02:00 AEST (+10) becomes 03:00 AEDT (+11), at 16:00Z on the 3rd.
# On the even-hour :57 grid, 00:57 AEST fires at 14:57Z, 02:57 does not exist,
# and 04:57 AEDT fires at 17:57Z. A naive +120-minute UTC grid would fire at
# 16:57Z and put the next reserve at 17:12Z.

SYDNEY = _cadence(timezone="Australia/Sydney")


def test_spring_forward_skips_the_missing_fire(tmp_path: Path) -> None:
    repo = _repo(tmp_path, SYDNEY)
    fired = datetime(2026, 10, 3, 14, 57, tzinfo=UTC)
    now = datetime(2026, 10, 3, 17, 15, tzinfo=UTC)
    code, payload = _routine(repo, fired, now)
    assert (code, payload.get("case")) == (1, "closed")
    assert payload.get("fired") == "2026-10-04T00:57:00+10:00"
    assert (payload.get("opens"), payload.get("closes")) == (
        "2026-10-04T05:42:00+11:00",
        "2026-10-04T07:12:00+11:00",
    )


def test_spring_forward_renders_each_instant_in_its_own_offset(tmp_path: Path) -> None:
    repo = _repo(tmp_path, SYDNEY)
    now = datetime(2026, 10, 3, 16, 30, tzinfo=UTC)
    code, payload = _attended(repo, now)
    assert (code, payload.get("case")) == (1, "not-yet")
    assert payload.get("now") == "2026-10-04T03:30:00+11:00"
    assert (payload.get("opens"), payload.get("closes")) == (
        "2026-10-04T05:12:00+11:00",
        "2026-10-04T05:42:00+11:00",
    )
    assert payload.get("routine_window") == {
        "opens": "2026-10-04T01:42:00+10:00",
        "closes": "2026-10-04T04:12:00+11:00",
    }


def test_fall_back_fires_the_repeated_time_once_at_its_earlier_occurrence(
    tmp_path: Path,
) -> None:
    """2027-04-04 03:00 AEDT (+11) becomes 02:00 AEST (+10), at 16:00Z on the 3rd,
    so 02:57 happens at 15:57Z and again at 16:57Z. A tick started at the second
    occurrence floors to the first; choosing the later would answer ``not-yet``."""
    repo = _repo(tmp_path, SYDNEY)
    fired = datetime(2027, 4, 3, 16, 57, tzinfo=UTC)
    now = datetime(2027, 4, 3, 16, 57, 30, tzinfo=UTC)
    code, payload = _routine(repo, fired, now)
    assert (code, payload.get("case")) == (0, "open")
    assert payload.get("fired") == "2027-04-04T02:57:00+11:00"
    assert (payload.get("opens"), payload.get("closes")) == (
        "2027-04-04T02:42:00+10:00",
        "2027-04-04T04:12:00+10:00",
    )


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


# --- AC-4: unreadable is never absent ----------------------------------------


@pytest.mark.parametrize(
    "config",
    [
        "cadence: {timezone: UTC, pitch: 120\n",
        "cadence:\n  timezone: UTC\n  routine:\n    open: 45\n",
        "cadence:\nother: x\n",
    ],
    ids=["unclosed-flow", "nested-sub-block", "empty-block"],
)
@pytest.mark.parametrize("run", ["routine", "attended", "train"])
def test_an_unreadable_block_refuses(tmp_path: Path, config: str, run: str) -> None:
    repo = _repo(tmp_path, config)
    args = ["--run", run, "--now", _z(_at(50))]
    if run != "attended":
        args += ["--fired", _z(T)]
    code, payload, _, err = _run(repo, *args)
    assert (code, payload.get("case")) == (2, "unreadable-cadence"), err
    assert payload.get("sources") == ["harness.yaml"]


# --- AC-5: invalid values refuse, naming the key -----------------------------


INVALID: dict[str, tuple[dict[str, str | None], str]] = {
    **{f"missing-{key}": ({key.replace(".", "__"): None}, key) for key in BASE},
    "pitch-not-dividing-a-day": ({"pitch": "100"}, "pitch"),
    "pitch-zero": ({"pitch": "0"}, "pitch"),
    "anchor-hour-24": ({"anchor": '"24:00"'}, "anchor"),
    "anchor-not-a-time": ({"anchor": "noon"}, "anchor"),
    "offset-with-a-unit": ({"routine__open": "45m"}, "routine.open"),
    "offset-fractional": ({"attended__close": "1.5"}, "attended.close"),
    "window-reversed": ({"routine__open": "135", "routine__close": "45"}, "routine.close"),
    "routine-longer-than-pitch": ({"routine__open": "0", "routine__close": "121"}, "routine.close"),
    "attended-longer-than-pitch": (
        {"attended__open": "0", "attended__close": "121"},
        "attended.close",
    ),
    "unknown-zone": ({"timezone": "Mars/Olympus"}, "timezone"),
    "negative-parked-limit": ({"parked_limit": "-1"}, "parked_limit"),
}


@pytest.mark.parametrize("name", sorted(INVALID))
def test_an_invalid_block_refuses_naming_the_key(tmp_path: Path, name: str) -> None:
    overrides, key = INVALID[name]
    repo = _repo(tmp_path, _cadence(**overrides))
    code, payload, _, err = _run(repo, "--run", "attended", "--now", _z(_at(50)))
    assert (code, payload.get("case"), payload.get("key")) == (2, "invalid-cadence", key), err
    assert payload.get("reason")


def test_an_invalid_block_refuses_a_train_too(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence(pitch="100"))
    code, payload, _, err = _run(repo, "--run", "train", "--fired", _z(T), "--now", _z(_at(50)))
    assert (code, payload.get("case"), payload.get("key")) == (2, "invalid-cadence", "pitch"), err


def test_a_reserve_overlapping_the_routine_window_is_accepted(tmp_path: Path) -> None:
    """The refusal set's boundary: unwise but well-defined is not refused."""
    repo = _repo(tmp_path, _cadence(attended__open="30", attended__close="60"))
    code, payload = _attended(repo, _at(50))
    assert (code, payload.get("case")) == (0, "open")
    assert payload.get("routine_window") == {"opens": _utc(_at(45)), "closes": _utc(_at(135))}


# --- usage --------------------------------------------------------------------


USAGE: dict[str, list[str]] = {
    "no-run": ["--now", "2026-10-07T11:47:00Z"],
    "unknown-run": ["--run", "nightly", "--now", "2026-10-07T11:47:00Z"],
    "routine-without-fired": ["--run", "routine", "--now", "2026-10-07T11:47:00Z"],
    "train-without-fired": ["--run", "train", "--now", "2026-10-07T11:47:00Z"],
    "train-fired-after-now": [
        "--run", "train", "--fired", "2026-10-07T12:00:00Z", "--now", "2026-10-07T11:47:00Z"
    ],
    "attended-with-fired": [
        "--run", "attended", "--fired", "2026-10-07T10:57:00Z", "--now", "2026-10-07T11:47:00Z"
    ],
    "now-without-offset": ["--run", "attended", "--now", "2026-10-07T11:47:00"],
    "fired-after-now": [
        "--run", "routine", "--fired", "2026-10-07T12:00:00Z", "--now", "2026-10-07T11:47:00Z"
    ],
    "unknown-flag": ["--run", "attended", "--when", "2026-10-07T11:47:00Z"],
}


@pytest.mark.parametrize("name", sorted(USAGE))
def test_usage_errors_exit_64_with_nothing_on_stdout(tmp_path: Path, name: str) -> None:
    repo = _repo(tmp_path, _cadence())
    code, _, out, err = _run(repo, *USAGE[name])
    assert (code, out) == (64, ""), err
    assert err.strip()


# --- AC-4: the source, and the root -------------------------------------------


@pytest.mark.parametrize(
    "harness_yaml", [None, ""], ids=["no-harness-yaml", "harness-yaml-without"]
)
def test_a_cadence_fenced_in_a_spine_is_not_read(tmp_path: Path, harness_yaml: str | None) -> None:
    repo = _repo(tmp_path, harness_yaml)
    (repo / "AGENTS.md").write_text("# Spine\n\n```yaml\n" + _cadence() + "```\n")
    code, payload, _, err = _run(repo, "--run", "attended", "--now", _z(_at(60)))
    assert (code, payload.get("case")) == (0, "no-cadence"), err


def test_repo_names_a_subdirectory_of_the_checkout(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _cadence())
    (repo / "sub").mkdir()
    code, payload, _, err = _run(
        tmp_path, "--repo", str(repo / "sub"), "--run", "attended", "--now", _z(_at(60))
    )
    assert (code, payload.get("case")) == (1, "not-yet"), err


def test_a_directory_outside_any_checkout_refuses(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    code, payload, _, err = _run(plain, "--run", "attended", "--now", _z(_at(60)))
    assert (code, payload.get("case")) == (2, "not-a-work-tree"), err

#!/usr/bin/env node
/**
 * May this train land now, and when does its window close (ADR 0024, on the
 * grid ADR 0023 introduced).
 *
 * A consumer on the landing train declares an optional `cadence:` block in
 * `harness.yaml`: the train's timetable. Trains depart every `pitch` minutes on
 * a grid of wall-clock times in a declared zone, and each train owns the
 * interval from its scheduled departure to the next one. Every run derives that
 * window from the declaration and the clock, so there is no shared state to go
 * stale and two runs reading the same clock cannot disagree. This file is the
 * one place that arithmetic lives; the skills call it rather than re-deriving a
 * window in prose.
 *
 * Usage, printing one JSON object on one line:
 *
 *     landing-window.js --run train --fired <instant> [--now <instant>] [--repo <dir>]
 *
 * `--fired` is the train's departure. It is matched to the latest scheduled
 * fire at or before it, so a train started late keeps its own slot and the
 * lateness only shortens its window. The window closes at the grid's next fire:
 * across a daylight-saving gap that is the next real fire, never the slot plus
 * the pitch. `--now` exists for tests. An instant must carry `Z` or an offset:
 * one without would be read in the host's zone, which is the disagreement this
 * file exists to remove. `--run` names the one run there is; ADR 0024 retired
 * ADR 0023's `routine` and `attended` runs, and naming either is a usage error.
 *
 * Exit codes follow the predicate convention, so `landing-window.js … && push`
 * behaves as today where no cadence is declared:
 *
 *   0  land now            `open`, or `no-cadence`
 *   1  do not land now     `closed`: the train's window has passed, it lands
 *                          nothing, and `closes` is its own
 *   2  refusal             `unreadable-cadence`, `invalid-cadence`, `not-a-work-tree`
 *   3  could not run       stderr only
 *   64 usage               stderr only
 *
 * A train's window opens at its slot, and the slot is never later than `--fired`
 * nor `--fired` than now, so no train is ever early.
 *
 * **Malformed is never absent.** A `cadence:` block the reader reports as
 * unreadable refuses, whatever else it returned; falling through to
 * `no-cadence` would land a consumer's runs on top of each other in silence.
 * Validation refuses only what leaves the grid undefined. A key other than
 * `timezone`, `anchor` and `pitch` is ignored, so a block declared under
 * ADR 0023 still reads, whatever its retired keys say.
 *
 * **Daylight saving.** Fires are the declared wall times. A wall time a
 * spring-forward gap skips does not fire; one a fall-back repeats fires once, at
 * its earlier occurrence.
 *
 * Node standard library only, CommonJS, run from the plugin root and never
 * materialized into a consumer (`.claude/rules/scripts.md`). It reads what is —
 * the declaration and the clock — and nothing that passed (ADR 0022 point 3).
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const MINUTE = 60 * 1000;
const DAY = 1440 * MINUTE;

//: Every key the block must declare, in the order validation reports them.
//: Any other key is ignored.
const KEYS = ["timezone", "anchor", "pitch"];

//: RFC 3339 with a mandatory `Z` or offset; seconds and fractions optional.
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/;

class Usage extends Error {}

class Invalid extends Error {
  constructor(key, value, reason) {
    super(reason);
    this.key = key;
    this.value = value;
  }
}

function config() {
  return require(path.join(__dirname, "harness-config.js"));
}

// --- the declaration ----------------------------------------------------------

function count(values, key) {
  const raw = values[key];
  if (!/^\d+$/.test(raw)) throw new Invalid(key, raw, "must be a non-negative whole number");
  return Number(raw);
}

/** The validated cadence, or an :class:`Invalid` naming the first bad key. */
function validate(values) {
  for (const key of KEYS) {
    if (!Object.hasOwn(values, key)) throw new Invalid(key, null, "is required");
  }
  const zone = values.timezone;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
  } catch (err) {
    void err;
    throw new Invalid("timezone", zone, "is not a time zone this host recognises");
  }
  const anchor = /^(\d{1,2}):(\d{2})$/.exec(values.anchor);
  if (anchor === null || Number(anchor[1]) > 23 || Number(anchor[2]) > 59) {
    throw new Invalid("anchor", values.anchor, "must be a time of day, H:MM or HH:MM");
  }
  const cadence = {
    zone,
    anchor: Number(anchor[1]) * 60 + Number(anchor[2]),
    pitch: count(values, "pitch"),
  };
  if (cadence.pitch === 0 || 1440 % cadence.pitch !== 0) {
    throw new Invalid("pitch", values.pitch, "must divide a day (1440 minutes) exactly");
  }
  return cadence;
}

// --- the clock ----------------------------------------------------------------

function formatter(zone) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** The wall-clock fields of ``ms`` in the formatter's zone. */
function wall(fmt, ms) {
  const fields = {};
  for (const part of fmt.formatToParts(new Date(ms))) fields[part.type] = Number(part.value);
  return {
    year: fields.year,
    month: fields.month,
    day: fields.day,
    hour: fields.hour % 24,
    minute: fields.minute,
    second: fields.second,
  };
}

/** The zone's offset from UTC at ``ms``, in milliseconds. */
function offsetAt(fmt, ms) {
  const w = wall(fmt, ms);
  const whole = ms - (((ms % 1000) + 1000) % 1000);
  return Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, w.second) - whole;
}

/** The instant of a wall time on a local date, the earlier where it repeats,
 * or ``null`` where a gap skips it. */
function wallToInstant(fmt, year, month, day, minuteOfDay) {
  const naive = Date.UTC(year, month - 1, day, 0, minuteOfDay);
  const offsets = new Set([naive - DAY, naive, naive + DAY].map((ms) => offsetAt(fmt, ms)));
  const hour = Math.floor(minuteOfDay / 60);
  const minute = minuteOfDay % 60;
  const found = [...offsets]
    .map((offset) => naive - offset)
    .filter((ms) => {
      const w = wall(fmt, ms);
      return w.year === year && w.month === month && w.day === day &&
        w.hour === hour && w.minute === minute;
    })
    .sort((a, b) => a - b);
  return found.length ? found[0] : null;
}

/** Every scheduled fire on the local dates spanning ``[from, to]``, ascending. */
function fires(cadence, fmt, from, to) {
  const first = wall(fmt, from);
  const last = wall(fmt, to);
  const lastDate = Date.UTC(last.year, last.month - 1, last.day);
  const found = new Set();
  for (let date = Date.UTC(first.year, first.month - 1, first.day); date <= lastDate; date += DAY) {
    const d = new Date(date);
    for (let k = 0; k < 1440 / cadence.pitch; k += 1) {
      const minuteOfDay = (cadence.anchor + k * cadence.pitch) % 1440;
      const ms = wallToInstant(fmt, d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate(), minuteOfDay);
      if (ms !== null) found.add(ms);
    }
  }
  return [...found].sort((a, b) => a - b);
}

/** ``ms`` as RFC 3339 in the zone, carrying the zone's offset at that instant. */
function render(fmt, ms) {
  const w = wall(fmt, ms);
  const offset = Math.round(offsetAt(fmt, ms) / MINUTE);
  const two = (n) => String(n).padStart(2, "0");
  const sign = offset < 0 ? "-" : "+";
  const abs = Math.abs(offset);
  return `${w.year}-${two(w.month)}-${two(w.day)}T${two(w.hour)}:${two(w.minute)}:` +
    `${two(w.second)}${sign}${two(Math.floor(abs / 60))}:${two(abs % 60)}`;
}

// --- the answer ---------------------------------------------------------------

function answer(cadence, run, now, fired) {
  const fmt = formatter(cadence.zone);
  // A pitch divides a day, so the slot and the next fire both lie within two
  // days of `fired` (a daily pitch whose fire a spring-forward skips leaves a
  // window of about 47 hours), and `fired` is never later than now.
  const grid = fires(cadence, fmt, fired - 2 * DAY, now + 2 * DAY);
  const at = (ms) => render(fmt, ms);
  const slot = grid.filter((fire) => fire <= fired).pop();
  if (slot === undefined) throw new Error("no scheduled fire precedes --fired");
  const closes = grid.find((fire) => fire > slot);
  if (closes === undefined) throw new Error("no scheduled fire follows the train's slot");
  const state = now < closes ? "open" : "closed";
  return {
    code: state === "open" ? 0 : 1,
    payload: { case: state, run, now: at(now), fired: at(slot), closes: at(closes) },
  };
}

// --- the command --------------------------------------------------------------

function instant(flag, text) {
  const ms = INSTANT.test(text) ? Date.parse(text) : NaN;
  if (Number.isNaN(ms)) {
    throw new Usage(`${flag} must be an RFC 3339 instant with Z or an offset, got ${JSON.stringify(text)}`);
  }
  return ms;
}

function parse(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i += 2) {
    const match = /^--(run|fired|now|repo)$/.exec(argv[i]);
    if (!match) throw new Usage(`unknown argument ${JSON.stringify(argv[i])}`);
    if (argv[i + 1] === undefined) throw new Usage(`${argv[i]} needs a value`);
    if (Object.hasOwn(options, match[1])) throw new Usage(`${argv[i]} given twice`);
    options[match[1]] = argv[i + 1];
  }
  if (options.run !== "train") {
    throw new Usage("--run must be train; ADR 0024 retired routine and attended");
  }
  const now = options.now === undefined ? Date.now() : instant("--now", options.now);
  if (options.fired === undefined) {
    throw new Usage("--run train needs --fired, the instant the train departed");
  }
  const fired = instant("--fired", options.fired);
  if (fired > now) throw new Usage("--fired is later than now");
  return { run: options.run, now, fired, repo: path.resolve(options.repo ?? process.cwd()) };
}

/** The checkout's root, or ``null`` where ``dir`` is in none. */
function topLevel(dir) {
  if (!fs.existsSync(dir)) return null;
  const result = spawnSync("git", ["rev-parse", "--show-toplevel"], { cwd: dir, encoding: "utf8" });
  if (result.error) throw result.error;
  return result.status === 0 ? result.stdout.trim() : null;
}

function run(options) {
  const top = topLevel(options.repo);
  if (top === null) {
    return {
      code: 2,
      payload: {
        case: "not-a-work-tree",
        run: options.run,
        repo: options.repo,
        reason: "the directory is not inside a git checkout, so there is no harness.yaml to read",
      },
    };
  }
  const unreadable = [];
  const values = config().declaredCadence(top, (source) => unreadable.push(path.relative(top, source)));
  if (unreadable.length) {
    return {
      code: 2,
      payload: {
        case: "unreadable-cadence",
        run: options.run,
        sources: unreadable,
        reason: "harness.yaml declares a cadence: block this reader cannot read, so no window can be derived",
      },
    };
  }
  if (Object.keys(values).length === 0) {
    return {
      code: 0,
      payload: {
        case: "no-cadence",
        run: options.run,
        reason: "harness.yaml declares no cadence: block, so every run lands when it is ready",
      },
    };
  }
  let cadence;
  try {
    cadence = validate(values);
  } catch (err) {
    if (!(err instanceof Invalid)) throw err;
    return {
      code: 2,
      payload: {
        case: "invalid-cadence",
        run: options.run,
        key: err.key,
        value: err.value,
        reason: `cadence ${err.key} ${err.message}`,
      },
    };
  }
  return answer(cadence, options.run, options.now, options.fired);
}

function main(argv) {
  try {
    const { code, payload } = run(parse(argv));
    process.stdout.write(`${JSON.stringify(payload)}\n`);
    return code;
  } catch (err) {
    if (err instanceof Usage) {
      process.stderr.write(`landing-window: ${err.message}\n`);
      return 64;
    }
    process.stderr.write(`landing-window: could not run: ${err && err.stack ? err.stack : err}\n`);
    return 3;
  }
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

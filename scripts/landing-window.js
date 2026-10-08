#!/usr/bin/env node
/**
 * May this run land now, and when does its window open and close (ADR 0023).
 *
 * A consumer that runs scheduled ticks on a shared integration branch declares
 * an optional `cadence:` block in `harness.yaml`. Ticks fire every `pitch`
 * minutes on a grid of wall-clock times in a declared zone; the tick that fired
 * owns a routine landing window measured from that fire, and attended work owns
 * a reserve measured the same way. Every run derives the windows from the
 * declaration and the clock, so there is no shared state to go stale and two
 * runs reading the same clock cannot disagree. This file is the one place that
 * arithmetic lives; the skills call it rather than re-deriving a window in prose.
 *
 * Usage, printing one JSON object on one line:
 *
 *     landing-window.js --run routine --fired <instant> [--now <instant>] [--repo <dir>]
 *     landing-window.js --run attended                  [--now <instant>] [--repo <dir>]
 *     landing-window.js --run train   --fired <instant> [--now <instant>] [--repo <dir>]
 *
 * A **train** (ADR 0024, #762) is the one land-only run on a cadence. It owns the
 * interval from its scheduled departure to the next one, so its window opens at
 * its slot and closes at the grid's next fire: across a daylight-saving gap that
 * is the next real fire, never the slot plus the pitch.
 *
 * `--fired` is the routine's or the train's own start instant. The clock alone cannot tell the
 * tick that fired at T asking at T+125 from the tick that fired at T+120 asking
 * at the same moment, because a routine window may run past the next fire. The
 * run is matched to the latest scheduled fire at or before `--fired`, so cron
 * running late keeps its own slot and the lateness only shortens its build.
 * `--now` exists for tests. An instant must carry `Z` or an offset: one without
 * would be read in the host's zone, which is the disagreement this file exists
 * to remove.
 *
 * Exit codes follow the predicate convention, so `landing-window.js … && push`
 * behaves as today where no cadence is declared:
 *
 *   0  land now            `open`, or `no-cadence`
 *   1  do not land now     `not-yet` (wait until `opens`), or `closed` (a
 *                          routine whose own window has passed: it parks, and
 *                          `opens`/`closes` name a later tick's window; or a
 *                          train whose window has passed: it lands nothing, and
 *                          `closes` is its own)
 *   2  refusal             `unreadable-cadence`, `invalid-cadence`, `not-a-work-tree`
 *   3  could not run       stderr only
 *   64 usage               stderr only
 *
 * **Malformed is never absent.** A `cadence:` block the reader reports as
 * unreadable refuses, whatever else it returned; falling through to
 * `no-cadence` would land a consumer's runs on top of each other in silence.
 * Validation refuses only what leaves the grid undefined or the answer
 * ambiguous; a reserve overlapping a routine window is unwise and well-defined,
 * and is accepted.
 *
 * **Daylight saving.** Windows are elapsed minutes from a fire, and fires are
 * the declared wall times. A wall time a spring-forward gap skips does not fire;
 * one a fall-back repeats fires once, at its earlier occurrence. Where two
 * windows of one kind then contain `now`, the earlier-fired one is reported.
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
const KEYS = [
  "timezone",
  "anchor",
  "pitch",
  "attended.open",
  "attended.close",
  "routine.open",
  "routine.close",
  "parked_limit",
];

const RUNS = ["routine", "attended", "train"];

//: The runs a window is found for by their own start instant.
const FIRED = ["routine", "train"];

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
    attended: { open: count(values, "attended.open"), close: count(values, "attended.close") },
    routine: { open: count(values, "routine.open"), close: count(values, "routine.close") },
    parkedLimit: count(values, "parked_limit"),
  };
  if (cadence.pitch === 0 || 1440 % cadence.pitch !== 0) {
    throw new Invalid("pitch", values.pitch, "must divide a day (1440 minutes) exactly");
  }
  for (const kind of ["routine", "attended"]) {
    const { open, close } = cadence[kind];
    const key = `${kind}.close`;
    if (open >= close) throw new Invalid(key, values[key], `must be later than ${kind}.open`);
    if (close - open > cadence.pitch) {
      throw new Invalid(key, values[key], `leaves a ${kind} window longer than the pitch`);
    }
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

function windowOf(fire, span) {
  return { opens: fire + span.open * MINUTE, closes: fire + span.close * MINUTE };
}

/** The earliest-fired window of ``span`` that has not closed by ``now``. */
function currentOrNext(grid, span, now, after = -Infinity) {
  for (const fire of grid) {
    if (fire <= after) continue;
    const window = windowOf(fire, span);
    if (window.closes > now) return window;
  }
  throw new Error("no window found in the enumerated range");
}

function answer(cadence, run, now, fired) {
  const fmt = formatter(cadence.zone);
  const reach = (Math.max(cadence.routine.close, cadence.attended.close) + cadence.pitch) * MINUTE;
  const grid = fires(cadence, fmt, Math.min(now, fired ?? now) - reach - 2 * DAY, now + reach + 2 * DAY);
  const at = (ms) => render(fmt, ms);

  if (run === "train") {
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

  if (run === "routine") {
    const slot = grid.filter((fire) => fire <= fired).pop();
    if (slot === undefined) throw new Error("no scheduled fire precedes --fired");
    let window = windowOf(slot, cadence.routine);
    let state = now < window.opens ? "not-yet" : now < window.closes ? "open" : "closed";
    if (state === "closed") window = currentOrNext(grid, cadence.routine, now, slot);
    return {
      code: state === "open" ? 0 : 1,
      payload: {
        case: state,
        run,
        now: at(now),
        fired: at(slot),
        opens: at(window.opens),
        closes: at(window.closes),
        parked_limit: cadence.parkedLimit,
      },
    };
  }

  const reserve = currentOrNext(grid, cadence.attended, now);
  const state = now < reserve.opens ? "not-yet" : "open";
  const routine = grid
    .map((fire) => windowOf(fire, cadence.routine))
    .find((window) => window.opens <= now && now < window.closes);
  return {
    code: state === "open" ? 0 : 1,
    payload: {
      case: state,
      run,
      now: at(now),
      opens: at(reserve.opens),
      closes: at(reserve.closes),
      routine_window: routine ? { opens: at(routine.opens), closes: at(routine.closes) } : null,
      parked_limit: cadence.parkedLimit,
    },
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
  if (!RUNS.includes(options.run)) throw new Usage("--run must be routine, attended or train");
  const now = options.now === undefined ? Date.now() : instant("--now", options.now);
  let fired = null;
  if (FIRED.includes(options.run)) {
    if (options.fired === undefined) {
      throw new Usage(`--run ${options.run} needs --fired, the instant the run started`);
    }
    fired = instant("--fired", options.fired);
    if (fired > now) throw new Usage("--fired is later than now");
  } else if (options.fired !== undefined) {
    throw new Usage("--fired applies to --run routine and --run train only");
  }
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

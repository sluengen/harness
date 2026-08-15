"""Is a run's actual diff certifiable without an LLM review? — #353.

The assurance policy (:mod:`harness.assurance`) decides what a *label* means.
This module decides what a *diff* means, and the two are deliberately separate
modules rather than two halves of one: ``assurance.py`` is pure over labels and
says so in its docstring, while the eligibility question is over paths and repo
configuration. Its shape follows :mod:`harness.gate` — one concern's config read
plus its pure helpers, in one module, called from a verb.

**The veto is code; the allowlist is configuration.** A repo declares what it is
willing to certify (``assurance.trivial_paths`` in ``CONTEXT.md``); the harness
holds back a table of surfaces no allowlist may open
(:data:`RESTRICTED_PATTERNS`). Narrowing is always available to a repo — it can
shrink its own allowlist — but widening past the veto is not, because a
repo-configurable restricted list would put the safety property under the control
of the input it is protecting against.

**Everything unresolved is ineligible**, and ineligible means the run upgrades to
``simple`` and takes an ordinary review. Absent config, invalid config, an
unreadable diff, an unknown boundary, and an empty change all answer the same
way. There is exactly one direction to fail in, and it is toward more
verification — so a bug here costs a fast path, never a gate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harness.layers import context_block

__all__ = [
    "CLASSIFIER_VERSION",
    "RESTRICTED_PATTERNS",
    "RESTRICTED_SURFACES",
    "AllowlistConfig",
    "IneligibilityReason",
    "TrivialEligibility",
    "classify_paths",
    "ineligible",
    "load_trivial_allowlist",
    "matches",
    "path_ineligibility",
    "validate_pattern",
]

#: Bumped whenever the classifier's answer for a fixed input could change.
#: Recorded on the certification event so a past certification can be read
#: against the rules that produced it, rather than against today's.
CLASSIFIER_VERSION = 1

#: How many offending paths a refusal carries. Bounded because the reason
#: reaches a tracker comment and a CLI payload, and a thousand-file diff has
#: already said what it needs to by the twentieth.
OFFENDING_PATHS_LIMIT = 20

#: Why a diff is not certifiable. Closed, and stable — these tags reach
#: ``CertifyOutput``, the tracker comment and the run row's ``assurance_reason``
#: lineage, so a consumer branches on them.
IneligibilityReason = Literal[
    "no_allowlist",  # absent, empty, or invalid ``assurance.trivial_paths``
    "gate_not_configured",  # the repo defines no ``verify:`` command
    "no_base_sha",  # the run carries no classification boundary
    "diff_unreadable",  # git could not answer
    "empty_diff",  # the run changed nothing
    "restricted_path",  # a path on a surface no allowlist may open
    "unlisted_path",  # a path no allowlist pattern matches
]

#: ``(pattern, surface)`` — the surfaces no allowlist may open. **Code,
#: deliberately not configuration** (module docstring). The surface strings are
#: the eight the ticket names, and :data:`RESTRICTED_SURFACES` is asserted
#: against them by test so a new pattern cannot arrive under an unguarded name.
RESTRICTED_PATTERNS: tuple[tuple[str, str], ...] = (
    # source — anything executed or interpreted
    ("*.py", "source"),
    ("*.pyi", "source"),
    ("*.sh", "source"),
    ("*.bash", "source"),
    ("*.zsh", "source"),
    ("*.ps1", "source"),
    ("*.js", "source"),
    ("*.mjs", "source"),
    ("*.ts", "source"),
    ("*.tsx", "source"),
    ("*.jsx", "source"),
    ("*.go", "source"),
    ("*.rs", "source"),
    ("*.rb", "source"),
    ("*.java", "source"),
    ("*.kt", "source"),
    ("*.swift", "source"),
    ("*.c", "source"),
    ("*.h", "source"),
    ("*.cc", "source"),
    ("*.cpp", "source"),
    ("*.hpp", "source"),
    ("*.cs", "source"),
    ("*.php", "source"),
    ("Makefile", "source"),
    ("Dockerfile", "source"),
    ("Procfile", "source"),
    # persistence
    ("*.sql", "persistence"),
    ("migrations/**", "persistence"),
    # configuration
    ("*.toml", "configuration"),
    ("*.yaml", "configuration"),
    ("*.yml", "configuration"),
    ("*.json", "configuration"),
    ("*.ini", "configuration"),
    ("*.cfg", "configuration"),
    ("*.lock", "configuration"),
    ("*.env", "configuration"),
    ("CONTEXT.md", "configuration"),
    (".github/**", "configuration"),
    ("docker/**", "configuration"),
    # security
    ("SECURITY.md", "security"),
    ("*.pem", "security"),
    ("*.key", "security"),
    ("*.crt", "security"),
    # command / guidance — the directories this guidance system owns everywhere
    ("commands/**", "command/guidance"),
    ("skills/**", "command/guidance"),
    ("agents/**", "command/guidance"),
    ("hooks/**", "command/guidance"),
    ("templates/**", "command/guidance"),
    ("settings/**", "command/guidance"),
    (".claude/**", "command/guidance"),
    # the as-built record and the decided record
    ("specs/features/**", "feature-spec"),
    ("specs/decisions/**", "decision"),
    # other public contract
    ("SPEC.md", "public-contract"),
    ("README.md", "public-contract"),
    ("LICENSE", "public-contract"),
    ("registry.yaml", "public-contract"),
    ("BOOTSTRAP.md", "public-contract"),
    ("scripts/**", "public-contract"),
)

#: The eight surfaces the ticket names. Declared rather than derived — the
#: ticket is the source, not the table — and the guard asserts every member is
#: reachable through :data:`RESTRICTED_PATTERNS` and that the table names no
#: other, so the two cannot drift in either direction.
RESTRICTED_SURFACES: frozenset[str] = frozenset(
    {
        "source",
        "security",
        "persistence",
        "configuration",
        "command/guidance",
        "feature-spec",
        "decision",
        "public-contract",
    }
)


# ---------------------------------------------------------------------------
# Pattern matching — three explicit forms, no glob library
# ---------------------------------------------------------------------------


def matches(path: str, pattern: str) -> bool:
    """Whether ``path`` matches ``pattern``. Three forms, and nothing else.

    * ``<prefix>/**`` — a directory rule: ``path`` equals ``prefix`` or begins
      with ``prefix + "/"``. The only recursive form.
    * ``*.<ext>`` — an extension rule: ``path`` ends with ``.<ext>``, at any depth.
    * anything else — an exact, whole-path match.

    Neither ``fnmatch`` nor :meth:`pathlib.PurePath.match` is used, and the
    reason is that both would decide a case nobody reasoned about: ``fnmatch``
    lets ``*`` cross ``/`` (so ``*.py`` would also match ``a/b.py`` only by
    accident of that same rule, and ``docs/*`` would match arbitrarily deep),
    while ``PurePath.match`` on 3.11 does not treat ``**`` as recursive at all.
    A pattern that silently widens is how a gate opens without anyone deciding
    to open it.

    Total: an unvalidated pattern cannot raise here, it simply matches nothing
    it should not. :func:`validate_pattern` is what refuses one at the boundary.
    """
    if pattern.endswith("/**"):
        prefix = pattern[: -len("/**")]
        return bool(prefix) and (path == prefix or path.startswith(prefix + "/"))
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return len(pattern) > 2 and path.endswith(suffix)
    return path == pattern


#: Characters no pattern may contain. ``#`` is here so an item's inline comment
#: can never be mistaken for part of a value, and whitespace so a pattern is a
#: single token the reader could not have split differently.
_FORBIDDEN_CHARS = ("#", "\\", "\0")


def validate_pattern(pattern: str) -> str | None:
    """Why ``pattern`` is unusable, or ``None`` if it is well-formed.

    The load-bearing rejection is the last one: a directory rule with an **empty
    prefix** (``**``, ``/**``, ``*/**``) would match every path in the repo, which
    is precisely the pattern a run would add to its own ``CONTEXT.md`` to certify
    itself. It is not expressible, and because one invalid pattern invalidates
    the whole list, writing it costs the run its fast path rather than buying it
    one.

    The tags are returned rather than raised because the caller records them:
    a refusal names which pattern was rejected and why.
    """
    if not pattern:
        return "empty"
    if any(char.isspace() for char in pattern):
        return "whitespace"
    if any(char in pattern for char in _FORBIDDEN_CHARS):
        return "forbidden_char"
    if pattern.startswith("/"):
        return "absolute"
    if ".." in pattern.split("/"):
        return "traversal"
    if pattern == "**":
        # The bare everything-rule, refused by name. It would also fall to the
        # catch-all below, but the tag is what a refusal reports, and
        # ``bad_glob`` would not tell an operator what they had actually written.
        # ``/**`` and ``*/**`` — the other two spellings of *everything* — are
        # already refused above (``absolute``) and below (``bad_glob``); there is
        # no fourth spelling, because the directory form requires a literal
        # prefix and every ``*`` outside the two allowed positions is rejected.
        return "empty_prefix"
    if pattern.endswith("/**"):
        # ``prefix`` cannot be empty here: that spelling is ``/**``, which the
        # leading-slash check above already refused.
        return "bad_glob" if "*" in pattern[: -len("/**")] else None
    if pattern.startswith("*."):
        rest = pattern[2:]
        return "bad_glob" if (not rest or "*" in rest or "/" in rest) else None
    return "bad_glob" if "*" in pattern else None


def path_ineligibility(path: str, allowlist: Sequence[str]) -> IneligibilityReason | None:
    """Why ``path`` is not certifiable, or ``None``.

    **The restricted scan runs first, and that ordering is the security
    property.** A restricted path answers ``restricted_path`` before any
    allowlist pattern is consulted, so no pattern — however broad — can launder
    one. Both scans live in this one function precisely so there is no call
    order for a caller to get wrong, and :func:`classify_paths` calls it rather
    than restating either half.
    """
    for pattern, _surface in RESTRICTED_PATTERNS:
        if matches(path, pattern):
            return "restricted_path"
    for pattern in allowlist:
        if matches(path, pattern):
            return None
    return "unlisted_path"


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrivialEligibility:
    """Whether a run's whole diff may be certified, and the evidence either way."""

    eligible: bool
    #: ``None`` iff :attr:`eligible`.
    reason: IneligibilityReason | None
    #: The paths that caused the refusal, sorted and bounded. Empty when eligible.
    offending_paths: tuple[str, ...] = ()
    #: The changed set, sorted — recorded on the certification event. Empty on a
    #: refusal, because there is nothing being attested to.
    eligible_paths: tuple[str, ...] = ()
    #: The patterns in force at classification time, recorded so a past
    #: certification can be read against the policy that produced it.
    allowlist: tuple[str, ...] = ()


def ineligible(
    reason: IneligibilityReason,
    *,
    paths: Sequence[str] = (),
    allowlist: Sequence[str] = (),
) -> TrivialEligibility:
    """The refusal constructor — one shape for every ineligible answer.

    The reasons the *verb* produces (``gate_not_configured``, ``no_base_sha``,
    ``diff_unreadable``) come through here rather than through a second dataclass,
    so every caller downstream reads one type.
    """
    return TrivialEligibility(
        eligible=False,
        reason=reason,
        offending_paths=tuple(sorted(paths))[:OFFENDING_PATHS_LIMIT],
        allowlist=tuple(allowlist),
    )


def classify_paths(paths: Sequence[str], allowlist: AllowlistConfig) -> TrivialEligibility:
    """Whether **every** changed path is certifiable. Total; never raises.

    The check order mirrors :func:`harness.assurance.resolve_assurance`'s
    documented one — the most general refusal first, so the answer names the
    root cause rather than a symptom:

    1. no valid allowlist — without a policy nothing is trivial, whatever the diff;
    2. no paths — a run that changed nothing has no content to attest to;
    3. per path, :func:`path_ineligibility`, the same function the table-driven
       test drives; the first reason encountered is reported, and every
       offending path is named.
    """
    if not allowlist.valid:
        return ineligible("no_allowlist")
    if not paths:
        return ineligible("empty_diff", allowlist=allowlist.patterns)

    reason: IneligibilityReason | None = None
    offending: list[str] = []
    for path in sorted(paths):
        this = path_ineligibility(path, allowlist.patterns)
        if this is not None:
            reason = reason or this
            offending.append(path)
    if reason is not None:
        return ineligible(reason, paths=offending, allowlist=allowlist.patterns)
    return TrivialEligibility(
        eligible=True,
        reason=None,
        eligible_paths=tuple(sorted(paths)),
        allowlist=tuple(allowlist.patterns),
    )


# ---------------------------------------------------------------------------
# The configuration surface — ``assurance.trivial_paths`` in CONTEXT.md
# ---------------------------------------------------------------------------

_ASSURANCE_HEADER = re.compile(r"^assurance:\s*(?:#.*)?$")
_TRIVIAL_PATHS_KEY = re.compile(r"^(\s+)trivial_paths:\s*(?:#.*)?$")
#: A list item, captured **loosely** on purpose: a malformed value must reach
#: :func:`validate_pattern` and invalidate the list, never be skipped by a
#: stricter regex that stops collecting and leaves the earlier entries in force.
_LIST_ITEM = re.compile(r"^(\s+)-(.*)$")
_INLINE_COMMENT = re.compile(r"\s+#.*$")


@dataclass(frozen=True)
class AllowlistConfig:
    """The repo's declared trivial allowlist, validated."""

    #: The patterns, or ``()`` whenever :attr:`valid` is false.
    patterns: tuple[str, ...]
    valid: bool
    #: Why it is unusable: ``no_block`` / ``no_key`` / ``empty`` /
    #: ``bad_pattern:<pattern>:<tag>``. ``None`` iff :attr:`valid`.
    invalid_reason: str | None = None


def _trivial_path_items(block: str) -> list[str] | None:
    """The raw ``trivial_paths:`` items, or ``None`` when the key is absent."""
    lines = block.splitlines()
    start: int | None = None
    key_indent = 0
    for index, line in enumerate(lines):
        match = _TRIVIAL_PATHS_KEY.match(line)
        if match is not None:
            start = index + 1
            key_indent = len(match.group(1))
            break
    if start is None:
        return None

    items: list[str] = []
    # No blank-line skip: :func:`~harness.layers.context_block` drops blank lines
    # from the body it returns rather than ending the block on one, so a blank
    # line between items never reaches here. ``blank-line-inside-the-list`` in
    # ``test_allowlist_configuration_table`` is what pins that composition.
    for line in lines[start:]:
        match = _LIST_ITEM.match(line)
        if match is None or len(match.group(1)) <= key_indent:
            break
        value = _INLINE_COMMENT.sub("", match.group(2)).strip()
        # Surrounding quotes are YAML's, not the pattern's — the same strip
        # ``layers.github_settings`` applies to its scalars. Without it a quoted
        # ``'docs/**'`` would be rejected as containing a forbidden character,
        # which fails safe but for a reason the operator could not guess; and,
        # worse, a quoted ``'**'`` would be refused as ``bad_glob`` rather than
        # as the everything-rule it is.
        items.append(value.strip("'\""))
    return items


def load_trivial_allowlist(repo_root: Path) -> AllowlistConfig:
    """The repo's ``assurance.trivial_paths``, validated. Never raises.

    An absent ``CONTEXT.md``, an absent ``assurance:`` block, an absent
    ``trivial_paths:`` key, an empty list, or **any** invalid pattern all answer
    ``valid=False`` with no patterns — so no diff is trivial.

    One bad pattern invalidates the whole list rather than being dropped.
    Silently discarding a pattern changes which paths are eligible with nothing
    failing, which is the failure mode this module exists to not have; and since
    the fail direction is toward ``simple``, strictness costs the repo an LLM
    review it was already paying for.
    """
    try:
        text = (repo_root / "CONTEXT.md").read_text()
    except OSError:
        return AllowlistConfig((), False, "no_block")
    block = context_block(text, _ASSURANCE_HEADER)
    if block is None:
        return AllowlistConfig((), False, "no_block")
    items = _trivial_path_items(block)
    if items is None:
        return AllowlistConfig((), False, "no_key")
    if not items:
        return AllowlistConfig((), False, "empty")
    for item in items:
        tag = validate_pattern(item)
        if tag is not None:
            return AllowlistConfig((), False, f"bad_pattern:{item}:{tag}")
    return AllowlistConfig(tuple(items), True, None)

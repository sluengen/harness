"""Shared git helpers for the verbs (CAL-606, CAL-610).

Two layers live here. :func:`run_git` is the generic *invocation* primitive —
the ``git -C <cwd> …`` argv prefix with ``check=False`` and
``capture_output=True`` — that every sync verb site shells out with. It returns
the :class:`subprocess.CompletedProcess` untouched so each caller keeps its own
error policy: raise a verb-specific exception, ignore the result for best-effort
cleanup, or inspect ``returncode`` directly. Centralising it means a change to
*how* the verbs call git (a flag, the binary path, NUL-terminated output) lands
once.

:func:`rev_parse_head` is a domain rule layered on top: ``review`` binds a
verdict to ``git rev-parse HEAD`` and ``close`` refuses to merge unless that
same SHA is still HEAD. That logic previously lived as byte-for-byte copies in
``review.py`` and ``close.py``, differing only in which verb-private exception
they raised. Giving the rule one home lets each caller re-raise :class:`GitError`
as its own verb-specific error.

**Why this is a top-level leaf and not ``harness/cli/_git.py`` (#269).** These
helpers are consumed from *below* the CLI as well as inside it —
:mod:`harness.close_merge`, :mod:`harness.promotion` and
:mod:`harness.promotion_pr` all call ``run_git``. While the module lived inside
the ``harness.cli`` package, importing it forced ``harness/cli/__init__.py`` to
run, and that eagerly imports every verb module — several of which import those
same three modules back. So entering the graph through any of them raised
``ImportError`` on a partially initialized module, and the failure was latent:
in a full-suite run something else imports ``harness.cli`` first, so the gate
stayed green and only a single-file ``pytest`` run ever hit it.

The module itself was never the problem — it imports only
:mod:`harness.branch_config` and :mod:`harness.identity`, both leaves, and has
never referenced anything under ``harness.cli``. It was simply mis-homed. Here,
beside :mod:`harness._time`, it sits below every consumer and the edges only
point down. ``tests/unit/test_import_layering.py`` fails the gate if a module
below the CLI reaches back into it.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path

from harness.branch_config import integration_branch
from harness.identity import WORKTREES_SUBDIR

# size: the shared git-invocation leaf every verb shells out through. #372
# pushed it past 500 by giving teardown the registry probe that tells a *locked*
# worktree from an orphaned directory — the two states ``git worktree remove``
# reports with the same exit code. That probe has to sit beside the teardown it
# discriminates for, and this module is already the one place below the CLI that
# owns "how the verbs talk to git". A seam does exist (invocation primitive vs.
# branch resolution vs. worktree teardown), and splitting on it would move five
# import sites — deliberately not folded into a bug fix. See #372's handoff.

#: The back-compat fallback base branch when neither CONTEXT.md nor the repo's
#: origin default resolves one — the harness's own integration branch (CAL-1106).
DEFAULT_BASE_BRANCH = "dev"

# Default ceiling (seconds) for a *network* git call — ``fetch`` / ``push`` /
# ``push --delete`` (CAL-1004). These reach a remote and can hang indefinitely on
# a partition or a wedged server; a local call (checkout, merge, rev-parse) does
# not and passes no timeout. 120s sits in the documented 60–120s band: generous
# for a healthy remote, bounded against a dead one. ``run_git`` forwards it to
# ``subprocess.run``, which raises ``subprocess.TimeoutExpired`` on expiry — each
# network site converts that into its own failure shape (never a raw traceback).
NETWORK_GIT_TIMEOUT_SECONDS = 120


class GitError(RuntimeError):
    """A git subprocess invocation failed.

    A plain :class:`RuntimeError` subclass so each verb can catch it and
    re-raise as its own control-flow exception (with the verb's exit code)
    without this module depending on either verb.
    """


def run_git(
    cwd: Path,
    *args: str,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``git -C <cwd> <args>`` capturing text output; never raise on non-zero.

    The shared invocation shape — the ``git -C`` prefix, ``check=False``,
    ``capture_output=True``, ``text=True`` — lives here so a change to how the
    verbs shell out to git lands once. Error handling stays with the caller: the
    :class:`subprocess.CompletedProcess` is returned untouched, so callers
    inspect ``returncode`` and raise their own verb-specific exception, ignore it
    (best-effort cleanup), or read the parsed output.

    ``timeout`` is forwarded as-is — a fired timeout raises
    :class:`subprocess.TimeoutExpired`, which the caller's guard handles; this
    helper does not swallow it.
    """
    # ``git`` is resolved from PATH (S607) and the args are list-form, never
    # ``shell=True`` (S603) — the same justification ``harness/cli/**`` carries
    # as a per-file-ignore for its own subprocess sites. Inline here because this
    # module sits outside that glob since #269; the two codes are reported on
    # different lines, so each needs its own marker.
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), *args],  # noqa: S607
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def git_common_dir(repo_root: Path) -> Path | None:
    """The resolved absolute ``.git`` common directory for ``repo_root``, or
    ``None`` when ``repo_root`` is not inside a git working tree.

    For the main checkout this is ``repo_root/.git``; for a linked worktree
    (``git worktree add``) it is the **main checkout's** ``.git`` — the shared
    state git itself resolves a worktree's ledger/refs/objects against. Callers
    that need the main checkout root read this dir's parent
    (:func:`resolve_ledger_root` in ``harness.cli._repo``).

    ``git rev-parse --git-common-dir`` prints an already-absolute path when the
    common dir lies outside ``repo_root`` (the worktree case) and a
    ``repo_root``-relative one otherwise (the main-checkout case, ``.git``) — so
    a relative result is joined onto ``repo_root`` before resolving. Returns
    ``None`` on any non-zero exit (not a git repo, ``repo_root`` does not exist)
    so a non-git caller falls back to its pre-existing behaviour.
    """
    result = run_git(repo_root, "rev-parse", "--git-common-dir")
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    common_dir = Path(raw)
    if not common_dir.is_absolute():
        common_dir = repo_root / common_dir
    return common_dir.resolve()


def worktree_toplevel_matches(worktree_path: Path) -> bool:
    """True iff ``git -C worktree_path rev-parse --show-toplevel`` resolves
    back to ``worktree_path`` itself.

    The anchoring guard every probe that reads ``git`` state *at a worktree* needs
    first. Without it, a directory whose worktree registration was already pruned
    (or that never was a proper worktree) has ``git`` walk **up** and report the
    *main checkout's* state instead. Both existing callers rely on that:
    ``worktrees cleanup --merged``'s stash / dirty-tree vetoes (#235) would
    otherwise veto an orphaned directory whenever the operator's own tree happens
    to be dirty, and ``reclaim --stale``'s worktree-mtime signal (#254) would read
    the main checkout's index — almost always freshly edited — and so spare every
    stale ticket, silently switching the sweep off.

    Lives here rather than in either caller because reaching into a command
    module's private helper is exactly what the CLI module-boundary guard forbids,
    and a second copy of a check whose failure mode is "the feature silently
    stops working" is worse than a shared one.
    """
    proc = run_git(worktree_path, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        return False
    try:
        return Path(proc.stdout.strip()).resolve() == worktree_path.resolve()
    except OSError:
        return False


#: Ceiling (seconds) for the ``git ls-files`` probe behind :func:`tracked_paths`.
#: A local call does not reach a remote, but both callers run on paths where a
#: wedged git must degrade to *no opinion* rather than hang: ``reclaim --stale``
#: is the Build routine's every-tick pre-flight, and ``review``'s pollution guard
#: sits in front of an engine it exists to keep from being reached slowly.
LS_FILES_TIMEOUT_SECONDS = 15


def tracked_paths(
    worktree_path: Path, *, timeout: float | None = LS_FILES_TIMEOUT_SECONDS
) -> list[str] | None:
    """The worktree-relative paths ``git`` tracks at ``worktree_path`` — or ``None``.

    Sync (it shells out); call it through :func:`asyncio.to_thread` from async
    code. ``None`` means *no opinion* and every caller must fail open on it: the
    path is not a directory, is not itself a git top-level, ``git ls-files``
    failed or timed out, or the index is empty.

    An empty index answers ``None`` rather than ``[]`` deliberately. ``[]`` reads
    as "0 tracked files", which is the one input that makes every file on disk
    look like excess — so the ambiguous case must not be representable as a
    measurement.

    The :func:`worktree_toplevel_matches` anchor is load-bearing, not defensive
    padding. ``git`` walks **up** from a directory whose worktree registration was
    pruned, so ``ls-files`` there reports the *main checkout's* index — whose
    files the operator is almost always editing. ``reclaim --stale`` would then
    read a fresh mtime for every stale ticket and silently switch itself off
    (#254); ``review``'s pollution guard would compare a worktree's on-disk count
    against a *different* tree's index and could refuse a clean run.

    Extracted here (#359) when that guard became the second caller of an
    enumeration ``reclaim_liveness.worktree_last_activity`` had owned privately.
    The two ask different questions — a newest mtime, and a file count — so only
    the enumeration and its anchor are shared; sharing them is what stops the two
    disagreeing about which paths are the worktree's own.
    """
    if not worktree_path.is_dir() or not worktree_toplevel_matches(worktree_path):
        return None
    try:
        proc = run_git(worktree_path, "ls-files", "-z", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        # Includes TimeoutExpired: a wedged git is no opinion, not a failure.
        return None
    if proc.returncode != 0:
        return None
    # ``-z`` is NUL-terminated, so a newline in a tracked filename cannot forge a
    # second entry. The trailing separator yields one empty field — skip it.
    names = [name for name in proc.stdout.split("\0") if name]
    return names or None


def diff_paths(
    worktree_path: Path,
    base_sha: str,
    *,
    timeout: float | None = LS_FILES_TIMEOUT_SECONDS,
) -> list[str] | None:
    """The worktree-relative paths changed by ``base_sha...HEAD`` — or ``None`` (#353).

    Sync (it shells out); call it through :func:`asyncio.to_thread` from async
    code. ``None`` means *no opinion*: the path is not a directory, is not itself
    a git top-level, or ``git diff`` failed, timed out, or could not resolve the
    boundary. The caller converts that to ``diff_unreadable`` — ineligible, so a
    run whose diff cannot be read takes an ordinary review.

    **Three-dot, not two.** ``base_sha...HEAD`` is the run's own side since the
    merge base, which is exactly what ``close`` merges, so a base branch that
    advanced mid-run cannot change the answer. That is a security property and
    not merely a stability one: it is what stops a run widening its allowlist in
    one commit and certifying itself in the next, because the widening commit is
    still inside the range being classified. A future "optimisation" to an
    incremental range would be a gate widening.

    Unlike :func:`tracked_paths`, an **empty** result is returned as ``[]`` and
    not folded into ``None``: "this run changed nothing" is a real,
    distinguishable answer here, and the classifier gives it its own refusal
    (``empty_diff``) rather than treating it as a failed probe.

    **``--no-renames`` is a gate mechanism, not a formatting preference.** Rename
    detection is on by default since git 2.9, and ``--name-only`` prints a
    detected rename as its **destination alone**. So moving ``harness/thing.py``
    to ``docs/thing.md`` would be reported as a single allowlisted path, and a
    change that deletes a source file would classify as trivial. With renames
    off, the same move is an add and a delete and both paths are judged.

    The :func:`worktree_toplevel_matches` anchor is the same trap
    :func:`tracked_paths` documents: git walks **up** from a directory whose
    worktree registration was pruned, so the diff would be computed against the
    enclosing checkout's HEAD — a tree nobody asked about.
    """
    if not worktree_path.is_dir() or not worktree_toplevel_matches(worktree_path):
        return None
    try:
        proc = run_git(
            worktree_path,
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            f"{base_sha}...HEAD",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        # Includes TimeoutExpired: a wedged git is no opinion, not a failure.
        return None
    if proc.returncode != 0:
        return None
    # ``-z`` is NUL-terminated, so a newline in a filename cannot forge an entry.
    return [name for name in proc.stdout.split("\0") if name]


def rev_parse_head(worktree_path: Path, *, timeout: float | None = None) -> str:
    """Return the current HEAD SHA of ``worktree_path`` (sync — run in a thread).

    Raises :class:`GitError` if ``git rev-parse HEAD`` exits non-zero.

    ``timeout`` is forwarded to :func:`run_git` and defaults to ``None`` — no
    ceiling — so ``close``, which runs interactively and wants a wedged git to be
    visible rather than silently reinterpreted, is unchanged. ``reclaim --stale``
    passes one because it runs as the Build routine's pre-flight every tick,
    where a hung probe would wedge the loop the sweep exists to unblock; a fired
    :class:`subprocess.TimeoutExpired` propagates for that caller's guard to
    catch (#255).
    """
    result = run_git(worktree_path, "rev-parse", "HEAD", timeout=timeout)
    if result.returncode != 0:
        raise GitError(
            f"git rev-parse HEAD failed for {worktree_path}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def origin_default_branch(repo_root: Path) -> str | None:
    """The repo's default branch per ``origin/HEAD``, or ``None`` if unresolvable.

    Reads ``git symbolic-ref refs/remotes/origin/HEAD`` (set by ``git clone``) and
    strips the ``refs/remotes/origin/`` prefix. Returns ``None`` when there is no
    ``origin`` remote or ``origin/HEAD`` was never recorded (e.g. a repo created
    with ``git init`` and a bare ``remote add`` but no clone) — a local call, no
    timeout needed. The caller supplies the fallback.
    """
    result = run_git(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD")
    if result.returncode != 0:
        return None
    ref = result.stdout.strip()
    prefix = "refs/remotes/origin/"
    branch = ref[len(prefix):] if ref.startswith(prefix) else ref
    return branch or None


def resolve_base_branch(repo_root: Path, explicit: str | None = None) -> str:
    """Resolve the base branch a run builds off / a merged worktree is reclaimed
    against, without hardcoding this repo's ``dev`` into a generic scaffold (CAL-1106).

    Resolution order (first hit wins):

    1. ``explicit`` — a caller-supplied value (``start --base``).
    2. ``branches.integration`` from the repo's CONTEXT.md
       (:func:`harness.branch_config.integration_branch`).
    3. The repo's actual default branch (:func:`origin_default_branch`).
    4. :data:`DEFAULT_BASE_BRANCH` (``"dev"``) — the back-compat fallback, so a
       repo that configures nothing behaves exactly as before.
    """
    return (
        explicit
        or integration_branch(repo_root)
        or origin_default_branch(repo_root)
        or DEFAULT_BASE_BRANCH
    )


def preferred_base_ref(repo_root: Path, base: str) -> str:
    """The most-current ref for ``base`` a reader should read: ``origin/<base>``
    when it resolves, else the local ``base`` branch (CAL-1154, Option 1).

    Since CAL-1154 ``close`` no longer advances the local ``<base>`` branch — it
    merges in a throwaway worktree and pushes ``origin/<base>``, which updates the
    local ``refs/remotes/origin/<base>`` tracking ref on the same machine with no
    fetch. So a reader that must see merged work — ``start`` basing a run worktree,
    ``worktrees cleanup --merged`` checking ancestry — reads ``origin/<base>``, not
    the local branch the merge no longer touches.

    Falls back to the local ``base`` when ``origin/<base>`` does not resolve — a
    repo with no ``origin`` remote, an offline clone, a fresh ``git init``, or the
    ``origin`` present but that branch never pushed — mirroring
    :func:`resolve_base_branch`'s fallback chain so those repos behave exactly as
    before. A local call, no timeout: it reads the already-fetched tracking ref
    (close's push keeps it current), never the network.
    """
    result = run_git(repo_root, "rev-parse", "--verify", "--quiet", f"origin/{base}")
    if result.returncode == 0:
        return f"origin/{base}"
    return base


class TeardownOutcome(StrEnum):
    """What :func:`teardown_worktree` did to the *worktree* half of its subject
    (#372). Returned, never raised — teardown stays best-effort (CAL-767), so a
    caller reporting a refusal reads this rather than re-deriving one from the
    filesystem, which cannot tell a survivor from a refusal.
    """

    #: ``git worktree remove --force`` succeeded: directory and entry both gone.
    RECLAIMED = "reclaimed"
    #: Nothing was registered at that path, so the directory on disk was cruft.
    ORPHAN_REMOVED = "orphan_removed"
    #: The worktree is locked. **Both halves were left alone.**
    LOCKED = "locked"
    #: Removal failed while the path is still registered, or the registry could
    #: not be read. Both halves left alone: a teardown that cannot tell which
    #: case it is in must not act.
    UNKNOWN = "unknown"
    #: Outside ``.worktrees/harness/`` — neither half was ever eligible.
    SKIPPED_AREA = "skipped_area"


def _registration_state(repo_root: Path, worktree_path: Path) -> str | None:
    """Is ``worktree_path`` still a registered worktree, and is it locked (#372)?

    ``"locked"`` / ``"registered"`` / ``"unregistered"``, or ``None`` for *no
    opinion* — git could not be read, so the caller must fail closed.

    The discriminator :func:`teardown_worktree` needs and never had.
    ``git worktree remove --force`` exits **128** both for a locked worktree and
    for a path git no longer tracks, and ``worktree_path.exists()`` is true of
    both — so neither can separate them. The registry can: porcelain prints a
    ``locked`` line inside a locked stanza and **omits an orphan's path
    entirely**. Structural, not textual — nothing here reads ``stderr``, whose
    wording drifts between git versions.

    ``Path.resolve()`` on both sides is load-bearing: porcelain emits
    **realpaths**, so a worktree added through a symlinked parent (``/tmp`` on
    macOS) is listed resolved, and a string comparison would miss its own
    stanza and report a locked worktree as an orphan to be destroyed.

    Output carrying no ``worktree`` stanza at all answers ``None``, not
    ``"unregistered"``: git always lists at least the main checkout, so an empty
    parse is a failed read — and the one answer that authorises a delete must
    never be reachable by failing to read.
    """
    parsed_any = False
    try:
        proc = run_git(repo_root, "worktree", "list", "--porcelain", timeout=15)
        if proc.returncode != 0:
            return None
        target = worktree_path.resolve()
        for stanza in proc.stdout.split("\n\n"):
            lines = stanza.splitlines()
            if not lines or not lines[0].startswith("worktree "):
                continue
            parsed_any = True
            if Path(lines[0][len("worktree "):]).resolve() != target:
                continue
            # ``locked`` bare, or ``locked <reason>`` when one was given.
            if any(ln == "locked" or ln.startswith("locked ") for ln in lines[1:]):
                return "locked"
            return "registered"
    except (OSError, subprocess.SubprocessError):
        # Includes TimeoutExpired: a wedged git is no opinion, not a failure.
        return None
    return "unregistered" if parsed_any else None


def _is_safe_branch_arg(branch: str) -> bool:
    """True iff ``branch`` is safe to pass as a git branch-name positional.

    A run's branch is ULID-shaped (``harness/<ULID>``), but a resumed run's name
    can originate in an untrusted tracker comment (the reclaim / handoff markers
    parsed in ``harness.linear``). Such a value is already argv-safe — every git
    call here is list-form, never ``shell=True`` — but a name with a leading
    ``-`` would be read by git as an *option*, not a branch (``git branch -D
    --all``). Refusing a ``-``-prefixed name at this sink neutralises that
    flag-injection without needing to trust the source (go-public security
    review). Real branch names (``harness/…``) are never dash-prefixed, so no
    legitimate teardown is affected.
    """
    return not branch.startswith("-")


def teardown_worktree(
    repo_root: Path,
    *,
    worktree_path: Path,
    branch: str | None = None,
    delete_remote: bool = False,
) -> TeardownOutcome:
    """Reclaim a run's worktree directory and branch — best-effort, never raises.

    One reclaim primitive for every site that finishes with a worktree it no
    longer needs: ``start`` rolling back a failed create, ``close`` after the
    merge has landed, and ``worktrees cleanup`` sweeping a merged run. It runs
    *after* the operation it follows has already succeeded, so a teardown failure
    must never mask or undo that — every git call ignores its result and no path
    here raises (CAL-767). What happened comes back as a
    :class:`TeardownOutcome` instead.

    Three steps: ``git worktree remove --force`` the directory *and* its admin
    entry, then ``git branch -D`` the local branch (when given), then
    ``git push origin --delete`` it when ``delete_remote`` (a checkpoint push
    may have created it). Step 1 runs whether or not the directory is present —
    git clears a registration whose directory is already gone, which keeps a
    stale entry from blocking a later ``git worktree add`` at that path — and on
    a refusal :func:`_registration_state` decides what happens next. Steps 2 and
    3 run on **every** step-1 outcome, ``LOCKED`` included: a lock is a
    statement about a directory and says nothing about a branch.

    **A lock is honoured, never overridden (#372).** ``git worktree remove
    --force`` refuses a locked worktree; the refusal is reported, not escalated
    — teardown never issues ``remove -f -f`` and never unlocks. Nor is it
    mistaken for an orphan: both refusals exit 128, so the discriminator is
    whether the path is *still registered*, never whether its directory exists.
    Only an **unregistered** path reaches :func:`shutil.rmtree` — the cruft a
    plain ``git worktree remove`` cannot touch. A path still registered, and a
    registry that cannot be read, both fail closed to ``UNKNOWN``: neither half
    touched, and the caller told.

    **Safety:** both halves are only ever touched for a path *inside*
    ``<repo_root>/.worktrees/harness/`` (``SKIPPED_AREA`` otherwise); a
    flag-like ``branch`` (leading ``-``) reaches neither branch step, which
    :func:`_is_safe_branch_arg` refuses so an untrusted, tracker-parsed name
    cannot be read by git as an option instead of a branch. That guard and the
    blast-radius contract behind step 1 (#371) — one named path, no repo-wide
    ``git worktree prune`` — are recorded in
    ``specs/features/worktree-lifecycle.md`` §*Teardown*.
    """
    worktrees_area = (repo_root / WORKTREES_SUBDIR).resolve()
    resolved = worktree_path.resolve()
    within_worktrees_area = (
        resolved != worktrees_area and worktrees_area in resolved.parents
    )
    outcome = TeardownOutcome.SKIPPED_AREA
    if within_worktrees_area:
        # Named path, not a sweep: this clears this worktree's admin entry and
        # provably no other, including one whose directory is unreachable from
        # the namespace we are running in (#371). Not gated on the directory
        # existing — a registration outliving its directory is the stale entry
        # the retired repo-wide prune used to collect.
        result = run_git(repo_root, "worktree", "remove", "--force", str(worktree_path))
        if result.returncode == 0:
            outcome = TeardownOutcome.RECLAIMED
        else:
            state = _registration_state(repo_root, worktree_path)
            if state == "unregistered":
                # git tracks nothing here, so whatever is on disk is cruft.
                shutil.rmtree(worktree_path, ignore_errors=True)
                outcome = TeardownOutcome.ORPHAN_REMOVED
            elif state == "locked":
                outcome = TeardownOutcome.LOCKED
            else:
                # Still registered, or the registry is unreadable — fail closed.
                outcome = TeardownOutcome.UNKNOWN
    if branch and _is_safe_branch_arg(branch):
        run_git(repo_root, "branch", "-D", branch)
        if delete_remote:
            # A network op — bound it (CAL-1004). Teardown is best-effort and
            # never raises (CAL-767), so a fired timeout is swallowed here like
            # any other non-zero exit on this cleanup path.
            with contextlib.suppress(subprocess.TimeoutExpired):
                run_git(
                    repo_root,
                    "push",
                    "origin",
                    "--delete",
                    branch,
                    timeout=NETWORK_GIT_TIMEOUT_SECONDS,
                )
    return outcome

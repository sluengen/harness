#!/usr/bin/env bash
# Emit a stamped harness client on stdout — the image's `install` role (#312).
#
# `~/bin/harness` has been a symlink into a live working tree, so the wrapper
# text in effect was whatever that tree currently held. A fix to the wrapper was
# therefore not live until the tree advanced — including the fix whose purpose
# was to advance it (#286's bootstrap case). This producer closes that: the
# client is emitted from an immutable image, so installing it needs neither a
# checkout, nor a network, nor the previous client to have worked.
#
#   docker run --rm harness:dev install --source-root <checkout> > ~/bin/harness.new && chmod +x ~/bin/harness.new && mv ~/bin/harness.new ~/bin/harness
#
# Write-then-rename, so an interrupted install cannot leave a truncated client on
# PATH. That command is written once here and once into every client's preamble,
# byte-identically, and `tests/unit/test_docs_consistency.py` derives it from this
# file rather than restating it — the docs carry the producer's own sentence.
#
# STDOUT IS THE ARTIFACT. Every diagnostic goes to stderr and every refusal emits
# nothing at all — the same discipline the shim applies to the verbs' JSON
# contract, and for the same reason: this stream is redirected straight onto the
# operator's PATH.
#
# There stays exactly ONE versioned shim. The body emitted below is the verbatim
# bytes of `harness-wrapper.sh`; a second, image-only client would be a second
# posture, which is the drift CAL-1123 named. What the preamble adds is two baked
# values and a provenance comment.
#
# Both files sit side by side — in the image at /opt/harness/, in the checkout at
# docker/ — so the template is resolved relative to this script rather than by an
# absolute path. That is what lets the host-side tests execute this same producer
# instead of a re-spelling of it.
set -euo pipefail

_here="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_template="$_here/harness-wrapper.sh"

_die() {
  echo "harness install: $1" >&2
  exit 2
}

_source_root=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root)
      [[ $# -ge 2 ]] || _die "--source-root needs a value"
      _source_root="$2"
      shift 2
      ;;
    --source-root=*)
      _source_root="${1#--source-root=}"
      shift
      ;;
    *)
      _die "unknown argument '$1' (usage: install [--source-root <absolute path>])"
      ;;
  esac
done

# The trust boundary, and the only one this role opens: the value below is
# interpolated into an emitted shell script. Single-quoting plus these two
# refusals is the COMPLETE defence — escaping the value instead would be a
# second, weaker mechanism for the same property.
#
# A relative root is refused for a different reason: the client runs from any
# directory, so a relative root silently mis-targets both the freshness guard and
# PYTHONPATH. That failure is invisible at run time, so it is caught here, where
# a human is watching.
if [[ -n "$_source_root" ]]; then
  [[ "$_source_root" == /* ]] ||
    _die "--source-root must be an absolute path, got '$_source_root'"
  if [[ "$_source_root" == *\'* || "$_source_root" == *$'\n'* ]]; then
    _die "--source-root may not contain a single quote or a newline"
  fi
fi

# A truncated image must fail loudly rather than emit half a client that fails at
# its first invocation, on the operator's machine, naming a line nobody wrote.
[[ -f "$_template" ]] ||
  _die "no client template at $_template — this image is incomplete"
[[ "$(head -c 2 "$_template")" == '#!' ]] ||
  _die "the client template at $_template is not a script"

# The image lays the manifest beside this script (/opt/harness/pyproject.toml);
# a checkout keeps it one level up from docker/. Both are looked for, so one
# producer serves both layouts.
_manifest="$_here/pyproject.toml"
[[ -f "$_manifest" ]] || _manifest="$_here/../pyproject.toml"
[[ -f "$_manifest" ]] ||
  _die "no package manifest near $_here — cannot stamp a version"
_version="$(awk -F'"' '/^version = "/ { print $2; exit }' "$_manifest")"
[[ -n "$_version" ]] || _die "no project version in $_manifest"

# `<package version>+<install instant>`, not the image digest: the digest is not
# knowable from inside the container without heuristics on /proc/self/cgroup,
# while this is knowable, monotone, and — unlike the bare package version, which
# changes only at release — distinguishes two installs made from one image.
_stamp="$_version+$(date -u +%Y%m%dT%H%M%SZ)"

cat <<PREAMBLE
#!/usr/bin/env bash
# The harness client, installed from the harness image — DO NOT EDIT.
# Version $_stamp. Everything below the second shebang is
# docker/harness-wrapper.sh verbatim; re-install rather than patching this file:
#   docker run --rm harness:dev install --source-root <checkout> > ~/bin/harness.new && chmod +x ~/bin/harness.new && mv ~/bin/harness.new ~/bin/harness
_harness_baked_client_version='$_stamp'
PREAMBLE

# Baked as a plain shell variable, deliberately NOT exported and deliberately not
# read from the environment: a non-exported assignment inside this script cannot
# be set by whatever process invokes the client, so "the checkout this client was
# built for" cannot be redirected by an ambient variable. Omitted entirely when
# no root was given — baking an empty value would arm the shim's branch on a
# value naming no checkout.
if [[ -n "$_source_root" ]]; then
  printf "_harness_baked_source_root='%s'\n" "$_source_root"
fi

cat "$_template"

"""CAL-749 — the registry's layer-gating note states an accurate contract.

Source: ``assessments/2026-06-16-mode2-dryrun.md`` DRYRUN-2 (Medium). The
brewspec Mode-2 dry-run omitted ``design-system`` + ``ux-design`` from the
install on the strength of the registry comment *"install-time layer gating is
CAL-675"* — but **CAL-675 is closed and is about ``/harness run`` universality,
not layer gating.** Install-time gating is unbuilt; the installer copies the
whole profile and the ``layers:`` block gates *engagement* at runtime, not
install membership. Omitting profile files drifts the consumer lock from the
registry (``/update-guidance`` would keep offering to re-add them).

These guards pin the corrected contract into ``registry.yaml`` so the comment
can't drift back to citing a closed/unrelated ticket as the gating mechanism.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "registry.yaml"

#: The stale claim the dry-run agent acted on — must not reappear.
STALE_GATING_CITE = "install-time layer gating is CAL-675"
#: The corrected contract: the layer gates engagement, not install membership.
CONTRACT_PHRASE = "install membership"


def test_registry_drops_the_stale_cal675_gating_cite() -> None:
    """registry.yaml no longer cites the closed/unrelated CAL-675 as gating."""
    assert STALE_GATING_CITE not in REGISTRY.read_text(), (
        f"registry.yaml still claims {STALE_GATING_CITE!r} — CAL-675 is closed "
        "and is about /harness run universality, not layer gating (CAL-749)."
    )


def test_registry_states_layers_gate_engagement_not_install() -> None:
    """registry.yaml states the layers gate engagement, not install membership."""
    assert CONTRACT_PHRASE in REGISTRY.read_text(), (
        "registry.yaml's product-skills note must state that the installer copies "
        f"the whole profile and layers gate engagement, not {CONTRACT_PHRASE!r} — "
        "so an installer agent does not omit profile files by layer (CAL-749)."
    )


def test_registry_keeps_ux_design_never_gated() -> None:
    """ux-design stays explicitly outside the design_system gate."""
    assert "independent of that layer" in REGISTRY.read_text(), (
        "registry.yaml must keep ux-design independent of the design_system "
        "layer — it applies to any user-facing surface and is never gated "
        "(CAL-749)."
    )

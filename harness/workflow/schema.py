"""Workflow / Step / Input Pydantic models — see SPEC §5.

These are the *engine-side* representations of a workflow YAML file. The loader
(H-008) parses YAML into these models and validates structure. Contract
compilation (inline YAML → Pydantic class) is H-006 — at this stage `contract`
is captured raw as either a string reference or a dict.

The Step type is a discriminated union over the documented `type:` field. Every
step in YAML must declare its type — including loop steps. The spec example
omitted `type: loop`; the spec table requires it. We follow the table.

Per-write merge overrides (H-1.5-004): the ``writes:`` list accepts either a
plain string (short-form, type-driven merge) or a dict with ``field`` and an
optional ``merge`` key (long-form). Both forms are normalised to
:class:`WriteSpec` at parse time so downstream code works with a single type.

Per-node retry configuration (H-1.5-005): each step may declare an optional
``retry:`` block that overrides v1's fixed defaults for that node only.
Currently only ``retry.transient.attempts`` is exposed.  Absent fields fall
through to the global :class:`~harness.engine.retry.RetryPolicy` defaults.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

# A contract is either a $contracts/<name> reference, a Tier-3 dotted Python
# import path, or an inline schema dict. Compilation lands in H-006; we just
# capture the raw form here.
ContractSpec: TypeAlias = str | dict[str, Any]


# ---------------------------------------------------------------------------
# Per-node retry configuration (H-1.5-005)
# ---------------------------------------------------------------------------


class RetryTransientConfig(BaseModel):
    """Transient-layer overrides for a single step.

    All fields are optional: ``None`` means "inherit from the global policy".
    Currently only ``attempts`` is exposed — further knobs (base delay, max
    delay) can be added here without breaking existing YAML.
    """

    model_config = ConfigDict(extra="forbid")

    attempts: int | None = Field(default=None, ge=1)


class RetryConfig(BaseModel):
    """Per-node retry configuration block (``retry:`` in YAML).

    Each sub-block is optional.  A step with no ``retry:`` key gets v1's
    fixed defaults from :meth:`~harness.engine.retry.RetryPolicy.v1_default`.
    """

    model_config = ConfigDict(extra="forbid")

    transient: RetryTransientConfig | None = None


def _is_non_empty(value: str | None) -> bool:
    """Treat ``None`` and ``""`` as "absent" for loop block satisfaction
    fields. Used by :class:`LoopBlock`'s ``until`` / ``until_bash``
    validator."""
    return value is not None and value != ""


# ---------------------------------------------------------------------------
# WriteSpec — per-write merge override (H-1.5-004)
# ---------------------------------------------------------------------------


class WriteSpec(BaseModel):
    """A single write declaration in a step's ``writes:`` list.

    Short-form ``writes: [plan]`` (a string) is normalised to
    ``WriteSpec(field="plan", merge=None)`` at :class:`_BaseStep` parse time.

    Long-form ``writes: [{field: plan, merge: replace}]`` explicitly sets a
    merge override that takes precedence over the type-driven default:

    * ``merge: replace`` — unconditional overwrite for any field type.
      Most useful for lists, which normally append.  Scalars already overwrite
      by default so ``replace`` is a no-op there, but it is accepted without
      error.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    merge: Literal["replace"] | None = None


def _normalise_writes(raw: list[Any]) -> list[WriteSpec]:
    """Convert a raw ``writes:`` list (mix of strings and dicts) to
    ``list[WriteSpec]``.  Pydantic's built-in coercion handles the dict→model
    path; we only need to handle the string shorthand.
    """
    result: list[WriteSpec] = []
    for item in raw:
        if isinstance(item, str):
            result.append(WriteSpec(field=item))
        elif isinstance(item, WriteSpec):
            result.append(item)
        else:
            # Let Pydantic validate the dict via model_validate so error
            # messages point at the right field.
            result.append(WriteSpec.model_validate(item))
    return result


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class InputSpec(BaseModel):
    """A workflow input, declared in `inputs:`. Drives CLI generation (§11)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "boolean"]
    required: bool = True
    default: Any = None
    pattern: str | None = None
    enum: list[Any] | None = None
    flag: str | None = None
    position: int | None = None

    @model_validator(mode="after")
    def _check_position_or_flag(self) -> InputSpec:
        if self.flag is not None and self.position is not None:
            raise ValueError(
                "an input cannot have both `flag` and `position` — pick one"
            )
        return self


# ---------------------------------------------------------------------------
# Step types — discriminated by `type:`
# ---------------------------------------------------------------------------


class _BaseStep(BaseModel):
    """Common fields every step has."""

    model_config = ConfigDict(extra="forbid")

    id: str
    depends_on: list[str] = Field(default_factory=list)
    writes: list[WriteSpec] = Field(default_factory=list)
    retry: RetryConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise_writes_field(cls, data: Any) -> Any:
        """Convert short-form string entries in ``writes:`` to WriteSpec dicts
        before Pydantic validates the model.  This runs on the raw input (a
        plain dict from YAML or a Python call-site) before field-level
        coercion, so both ``writes: ["plan"]`` and
        ``writes: [{field: plan, merge: replace}]`` produce
        ``list[WriteSpec]``.
        """
        if isinstance(data, dict) and "writes" in data:
            raw_writes = data["writes"]
            if isinstance(raw_writes, list):
                data = {**data, "writes": _normalise_writes(raw_writes)}
        return data


class AIStep(_BaseStep):
    type: Literal["ai"]
    agent: str | None = None
    model: str | None = None
    prompt: str
    template_vars: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Grep", "Glob"]
    )
    contract: ContractSpec | None = None
    cwd: str | None = None
    writes_files: bool = False
    stall_timeout_s: int = 300
    timeout_s: int = 600
    max_turns: int | None = Field(default=None, ge=1)
    persist_session: bool = False
    """Carry the agent's conversation across loop iterations.

    When ``True``, the agent adapter resumes the same session on each
    re-execution of this step (keyed by ``step.id``) instead of starting
    fresh — so a retried implement agent keeps the reasoning and history of
    its prior attempt. Default ``False`` (fresh each call) preserves the
    stateless behaviour reviewers and one-shot steps want. Honoured by
    adapters that support session resume (ClaudeAgent); others ignore it.
    A ``fresh_context: true`` loop clears stored sessions via ``reset()``.
    """


class ScriptStep(_BaseStep):
    type: Literal["script"]
    command: str | None = None
    script: str | None = None
    runtime: Literal["bash", "python"] = "bash"
    args: list[str] = Field(default_factory=list)
    contract: ContractSpec | None = None
    cwd: str | None = None
    writes_files: bool = False

    @model_validator(mode="after")
    def _check_command_or_script(self) -> ScriptStep:
        if self.command is None and self.script is None:
            raise ValueError(
                "script step must declare either `command` or `script`"
            )
        if self.command is not None and self.script is not None:
            raise ValueError(
                "script step cannot declare both `command` and `script`"
            )
        return self


class CheckStep(_BaseStep):
    type: Literal["check"]
    expr: str
    on_fail: str = "cancel"  # cancel | continue | retry_loop:<id>


class DecisionStep(_BaseStep):
    type: Literal["decision"]
    actor: Literal["llm", "human"]
    on_reject: str = "cancel"  # cancel | continue | retry_loop:<id> | pause_for_human

    # actor: llm fields
    agent: str | None = None
    model: str | None = None
    prompt: str | None = None
    template_vars: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    contract: ContractSpec | None = None
    cwd: str | None = None

    # actor: human fields (v2)
    via: Literal["cli", "webhook"] | None = None
    message: str | None = None
    display_state: list[str] = Field(default_factory=list)
    timeout: str | None = None  # duration like "24h"
    on_timeout: Literal["cancel", "continue", "reject_and_continue"] = "cancel"

    @model_validator(mode="after")
    def _check_actor_fields(self) -> DecisionStep:
        if self.actor == "llm" and self.prompt is None:
            raise ValueError("decision actor=llm requires `prompt`")
        if self.actor == "human" and self.message is None:
            raise ValueError("decision actor=human requires `message`")
        return self


class WorktreeStep(_BaseStep):
    type: Literal["worktree"]
    action: Literal["create", "cleanup"]
    base: str | None = None
    policy: (
        Literal["merge_to_base", "leave_for_inspection", "delete_unconditionally"]
        | None
    ) = None

    @model_validator(mode="after")
    def _check_action_fields(self) -> WorktreeStep:
        if self.action == "create" and self.base is None:
            raise ValueError("worktree action=create requires `base`")
        if self.action == "cleanup" and self.policy is None:
            raise ValueError("worktree action=cleanup requires `policy`")
        return self


class LoopBlock(BaseModel):
    """The `loop:` payload on a LoopStep. Holds the iteration spec + child steps."""

    model_config = ConfigDict(extra="forbid")

    max_iterations: int = Field(gt=0)
    # Exactly one of ``until`` / ``until_bash`` must be set. The empty string is
    # treated as "absent" so workflows that historically declared
    # ``until: ""`` alongside ``until_bash:`` (the pre-H-021b workaround for
    # ``until`` being required) keep validating. The combined-fields case is
    # rejected by :class:`harness.engine.loop.LoopExecutor` at run time so the
    # message names the offending step.
    until: str | None = None
    fresh_context: bool = False
    until_bash: str | None = None
    # ``cancel`` (default): LoopExhausted propagates and the workflow fails.
    # ``continue``: fall through to post-loop steps when max_iterations is
    # reached without ``until`` becoming true. Backwards-compatible: existing
    # workflows that omit this field get the original cancel behaviour.
    on_exhaust: Literal["cancel", "continue"] = "cancel"
    steps: list[Step]

    @model_validator(mode="after")
    def _check_until_or_until_bash(self) -> LoopBlock:
        if not _is_non_empty(self.until) and not _is_non_empty(self.until_bash):
            raise ValueError(
                "loop block must declare `until:` or `until_bash:` "
                "(or both, subject to engine rejection of the combined form)"
            )
        return self


class LoopStep(_BaseStep):
    type: Literal["loop"]
    loop: LoopBlock


# Discriminated union over the `type` field.
Step = Annotated[
    AIStep | ScriptStep | CheckStep | DecisionStep | WorktreeStep | LoopStep,
    Field(discriminator="type"),
]

# Resolve the forward reference inside LoopBlock.steps.
LoopBlock.model_rebuild()


# ---------------------------------------------------------------------------
# Workflow root
# ---------------------------------------------------------------------------


class Workflow(BaseModel):
    """A workflow YAML file as a Pydantic model. Loader (H-008) produces this."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: int = Field(ge=1)
    description: str = ""
    inputs: dict[str, InputSpec] = Field(default_factory=dict)
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_step_ids(self) -> Workflow:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError(f"workflow has duplicate step ids: {ids}")
        return self

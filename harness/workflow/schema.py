"""Workflow / Step / Input Pydantic models — see SPEC §5.

These are the *engine-side* representations of a workflow YAML file. The loader
(H-008) parses YAML into these models and validates structure. Contract
compilation (inline YAML → Pydantic class) is H-006 — at this stage `contract`
is captured raw as either a string reference or a dict.

The Step type is a discriminated union over the documented `type:` field. Every
step in YAML must declare its type — including loop steps. The spec example
omitted `type: loop`; the spec table requires it. We follow the table.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

# A contract is either a $contracts/<name> reference, a Tier-3 dotted Python
# import path, or an inline schema dict. Compilation lands in H-006; we just
# capture the raw form here.
ContractSpec: TypeAlias = str | dict[str, Any]


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
    writes: list[str] = Field(default_factory=list)


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
    until: str
    fresh_context: bool = False
    until_bash: str | None = None
    steps: list[Step]


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

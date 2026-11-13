from typing import Literal, Optional, Union

from pydantic import BaseModel, TypeAdapter


class SetField(BaseModel):
    type: Literal["set_field"]
    step_id: str
    key: str
    value: Union[float, bool, str]


class Perform(BaseModel):
    type: Literal["perform"]
    step_id: str


class Abort(BaseModel):
    type: Literal["abort"]


class ManualStart(BaseModel):
    type: Literal["manual_start"]


class SetTimeScale(BaseModel):
    type: Literal["set_time_scale"]
    value: float      # 1 to 50


class SetReference(BaseModel):
    type: Literal["set_reference"]
    on: bool


class ActionResult(BaseModel):
    ok: bool
    error: Optional[str] = None


Action = Union[SetField, Perform, Abort, ManualStart, SetTimeScale, SetReference]

_ACTION_ADAPTER: TypeAdapter = TypeAdapter(Action)


def parse_action(raw: dict) -> Action:
    """Validate a raw dict as one action; raises pydantic ValidationError on anything else."""
    return _ACTION_ADAPTER.validate_python(raw)

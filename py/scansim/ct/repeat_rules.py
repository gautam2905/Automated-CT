"""When a step that is already done may be done again.

These are `check` functions (see `core.steps.Step`): each returns the reasons a step cannot be performed.
A done step with a reason is shown as not repeatable and its fields are locked.
"""
from typing import Callable

from scansim.core.steps import Step
from scansim.ct.context import CTContext

Check = Callable[[CTContext, Step], list[str]]


def before_injection(ctx: CTContext, step: Step) -> list[str]:
    """Nothing that led up to the injection can be done again once the contrast is in the patient."""
    if ctx.injector.started_at_s is None:
        return []
    return [f'The injection has started, so "{step.title}" cannot be done again: the contrast phases that '
            "follow from it cannot be repeated"]


def all_of(*checks: Check) -> Check:
    def combined(ctx: CTContext, step: Step) -> list[str]:
        return [reason for check in checks for reason in check(ctx, step)]
    return combined

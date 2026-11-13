"""One way to make a step whose id, title, actor and place come from the sample snapshot's table."""
from scansim.core.steps import Step
from scansim.ct.workflow_prescan import sample_step


def make_step(step_id: str, info: str, routine, fields=(), **kwargs) -> Step:
    stage_id, title, actor, place, _ = sample_step(step_id)
    return Step(step_id, stage_id, title, actor=actor, place=place, info=info, fields=fields, routine=routine,
                **kwargs)

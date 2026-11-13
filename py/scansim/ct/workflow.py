"""All eleven stages of the CT exam, assembled from three step builders.

`prescan_steps` (workflow_prescan.py) builds the first eighteen steps. `scan_steps` is the topogram, planning
and non-contrast steps (workflow_scan.py) plus the tracking set-up (workflow_tracking.py). `contrast_steps`
(workflow_contrast.py) is the contrast phases, with the review (workflow_review.py) and aftercare
(workflow_aftercare.py) stages.

A builder returns plain steps. Steps that leave `requires` empty are chained to the step before them in
the full order, so a builder only states a prerequisite when it differs from "the previous step".
"""
from scansim.core.steps import Step, Workflow
from scansim.ct.context import CTContext
from scansim.ct.workflow_contrast import contrast_steps
from scansim.ct.workflow_prescan import STAGE_TITLES, prescan_steps
from scansim.ct.workflow_scan import scan_steps as _noncontrast_steps
from scansim.ct.workflow_tracking import tracking_steps
from scansim.examples import _STAGES as _SAMPLE_STAGES

STAGE_ORDER = tuple(stage_id for stage_id, _, _ in _SAMPLE_STAGES)


def scan_steps(ctx: CTContext) -> list[Step]:
    """Topogram, planning, non-contrast scan and the tracking set-up."""
    return [*_noncontrast_steps(ctx), *tracking_steps(ctx)]


def _chain(steps: list[Step]) -> None:
    for previous, step in zip(steps, steps[1:]):
        if not step.requires:
            step.requires = (previous.id,)


def _stages(steps: list[Step]) -> list[tuple[str, str, list[Step]]]:
    by_stage: dict[str, list[Step]] = {stage_id: [] for stage_id in STAGE_ORDER}
    for step in steps:
        if step.stage_id not in by_stage:
            raise ValueError(f"Step {step.id!r} is in unknown stage {step.stage_id!r}")
        by_stage[step.stage_id].append(step)
    return [(stage_id, STAGE_TITLES[stage_id], by_stage[stage_id]) for stage_id in STAGE_ORDER]


def build_ct_workflow(ctx: CTContext) -> Workflow:
    steps = [*prescan_steps(ctx), *scan_steps(ctx), *contrast_steps(ctx)]
    _chain(steps)
    return Workflow(_stages(steps), ctx.scheduler, ctx.log)

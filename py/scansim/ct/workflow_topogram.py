"""The two topograms and the centring check.

A topogram covers `start_mm` to `start_mm + length_mm` in the planning coordinate. The table moves under
a parked tube and the image grows row by row; `revealed_*_row` follow the table. Rows are numbered head to
feet, and the table runs whichever way the placement needs to bring the head end into the beam first.

ASSUMPTIONS: none of the numbers here are new. Topogram dose is not added to the exam DLP: research note 01
section B gives it only as an effective dose (0.04 to 0.42 mSv per localizer), not as a DLP.
"""
import math
from typing import Generator

import numpy as np

from scansim.core.fields import Field
from scansim.core.process import Until
from scansim.core.steps import Step, StepError
from scansim.ct.acquisition import (HOLD_TIMEOUT_S, RELEASE_VOICE, require_room_ready, require_table_travel,
                                    start_breath_hold, sweep, switch_everything_off)
from scansim.ct.context import CTContext
from scansim.ct.repeat_rules import all_of, before_injection
from scansim.ct.scan_fields import NumericChoiceField, number_field, source_for
from scansim.ct.workflow_prescan import sample_step
from scansim.patient.pack import OutsideAnatomy
from scansim.snapshot import TopogramView

TOPOGRAM_PHASE = "inspiration"
TUBE_ABOVE_DEG = 0.0
TUBE_AT_PLUS_X_DEG = 90.0
TUBE_AT_MINUS_X_DEG = 270.0
MA_RANGE = (1.0, 500.0)
START_LIMIT_MM = 1500.0
COPIED_KEYS = ("kv", "ma", "start_mm", "length_mm")


# ---- geometry ----

def tube_angle_deg(ctx: CTContext, view: str) -> float:
    """0 for the tube above the patient; the lateral view has it on the patient's left."""
    if view == "AP":
        return TUBE_ABOVE_DEG
    # Supine and feet first, the patient's left is at -x; either turn (head first, or prone) flips it.
    left_is_minus_x = (ctx.entry == "feet_first") == (ctx.orientation == "supine")
    return TUBE_AT_MINUS_X_DEG if left_is_minus_x else TUBE_AT_PLUS_X_DEG


def _rows_for(ctx: CTContext, view: str, start_mm: float, length_mm: float) -> tuple[int, int, float]:
    """(first row, row count, planning coordinate of row 0); the rows cover at least the requested run."""
    topo = ctx.pack.topogram(view)
    row0_mm = topo.z_body_of_row0 - ctx.landmark_z_body_mm
    first = math.floor((start_mm - row0_mm) / topo.row_mm + 1e-9)
    count = math.ceil(length_mm / topo.row_mm - 1e-9)
    rows = topo.pixels.shape[0]
    if first < 0 or first + count > rows:
        raise StepError(f"The {view} topogram image covers {row0_mm:.0f} to {row0_mm + rows * topo.row_mm:.0f} mm; "
                        f"{start_mm:.0f} to {start_mm + length_mm:.0f} mm does not fit")
    return first, count, row0_mm


def _require_anatomy(ctx: CTContext, start_mm: float, end_mm: float) -> None:
    top, bottom = ctx.pack.data_range_mm
    landmark = ctx.landmark_z_body_mm
    if ctx.body_z(start_mm) < top or ctx.body_z(end_mm) > bottom:
        raise StepError(f"Topogram {start_mm:.0f} to {end_mm:.0f} mm goes past the patient's CT data: "
                        f"no anatomy data beyond {top - landmark:.0f} mm (head end) or "
                        f"{bottom - landmark:.0f} mm (feet end) from the landmark")


def span_mm(view: TopogramView) -> tuple[float, float]:
    """Planning coordinates covered by the rows revealed so far."""
    return (view.row0_from_landmark_mm + view.revealed_from_row * view.row_mm,
            view.row0_from_landmark_mm + view.revealed_to_row * view.row_mm)


def complete_topogram(ctx: CTContext, view: str) -> TopogramView:
    for topo in ctx.console.topograms:
        if topo.view == view and topo.complete:
            return topo
    raise StepError(f"Acquire a complete {view} topogram first")


# ---- the acquisition ----

class _Rows:
    """Which rows of the topogram image are revealed, as the table covers `distance` of the run."""

    def __init__(self, ctx: CTContext, view: str, start_mm: float, length_mm: float, forward: bool) -> None:
        self.ctx, self.view, self.forward = ctx, view, forward
        self.first, self.count, self.row0_mm = _rows_for(ctx, view, start_mm, length_mm)
        self.length_mm = length_mm

    def publish(self, revealed: int, complete: bool = False) -> None:
        """Show `revealed` rows, growing from the head end (or from the feet end if run caudocranial)."""
        ctx, topo = self.ctx, self.ctx.pack.topogram(self.view)
        end = self.first + self.count
        from_row, to_row = (self.first, self.first + revealed) if self.forward else (end - revealed, end)
        edge = to_row if self.forward else from_row         # the edge that moves; it keys the image URL
        ctx.console.set_topogram(TopogramView(
            view=self.view, image_url=ctx.console.topogram_url(self.view, edge), rows=topo.pixels.shape[0],
            cols=topo.pixels.shape[1], row_mm=topo.row_mm, col_mm=topo.col_mm,
            row0_from_landmark_mm=self.row0_mm, revealed_from_row=from_row, revealed_to_row=to_row,
            complete=complete))

    def grow(self, fraction: float) -> None:
        row_mm = self.ctx.pack.topogram(self.view).row_mm
        self.publish(min(self.count, math.ceil(fraction * self.length_mm / row_mm - 1e-9)))


def _acquire(ctx: CTContext, step: Step, view: str) -> Generator:
    require_room_ready(ctx)
    start, length = step.value("start_mm"), step.value("length_mm")
    _require_anatomy(ctx, start, start + length)
    forward = ctx.protocol.topogram.direction == "craniocaudal"
    first_mm, last_mm = (start, start + length) if forward else (start + length, start)
    long_first, long_last = require_table_travel(ctx, first_mm, last_mm, f"The {view} topogram")
    rows = _Rows(ctx, view, start, length, forward)
    earlier = next((t for t in ctx.console.topograms if t.view == view), None)
    hold, finished = None, False
    try:
        yield from ctx.table.move_long(long_first)
        hold = start_breath_hold(ctx, TOPOGRAM_PHASE)
        yield Until(lambda: ctx.breathing.holding, HOLD_TIMEOUT_S)
        ctx.tube_angle_deg, ctx.kv, ctx.ma = tube_angle_deg(ctx, view), int(step.value("kv")), step.value("ma")
        ctx.room.warning_light_on = ctx.beam_on = True
        rows.publish(0)
        yield from sweep(ctx, long_last, ctx.spec.topogram.speed_mm_s, rows.grow)
        rows.publish(rows.count, complete=True)
        finished = True
    finally:
        switch_everything_off(ctx, hold)
        if not finished:        # an aborted run leaves the earlier view as it was, or none if there was none
            ctx.console.topograms = [t for t in ctx.console.topograms if t.view != view]
            if earlier is not None:
                ctx.console.set_topogram(earlier)
    ctx.say(RELEASE_VOICE)


# ---- steps ----

def _fields(ctx: CTContext, view: str) -> list[Field]:
    topo, scanner = ctx.protocol.topogram, ctx.spec.topogram
    return [
        NumericChoiceField("kv", "Tube voltage", topo.kv, scanner.kv_options, source=source_for(ctx.protocol, "topogram.kv"),
                           unit="kV"),
        number_field("ma", "Tube current", topo.ma, source_for(ctx.protocol, "topogram.ma"), unit="mA",
                     lo=MA_RANGE[0], hi=MA_RANGE[1], help="Low on purpose: the topogram only needs a rough picture."),
        number_field("start_mm", "Start", topo.start_from_landmark_mm,
                     source_for(ctx.protocol, "topogram.start_from_landmark_mm"), unit="mm",
                     lo=-START_LIMIT_MM, hi=START_LIMIT_MM,
                     help="From the landmark; negative is toward the head."),
        NumericChoiceField("length_mm", "Length", topo.length_mm, scanner.lengths_mm,
                           source=source_for(ctx.protocol, "topogram.length_mm"), unit="mm"),
    ]


def _copy_values(source: dict[str, Field], target: dict[str, Field]) -> None:
    for key in COPIED_KEYS:
        target[key].value = source[key].value


def _height_field(ctx: CTContext) -> Field:
    spec = ctx.spec.table
    return Field("new_height_mm", "Table height", "number", ctx.table.height_mm, source="computed", unit="mm",
                 min=spec.height_min_mm, max=spec.height_max_mm, step=1.0,
                 help="Starts at the current height. Change it to move the table after you have judged the centring.")


def _sync_height(ctx: CTContext, height: Field) -> None:
    height.value = height.default = round(ctx.table.height_mm, 1)


def _body_centre_offset_mm(ctx: CTContext, topo: TopogramView) -> float:
    """Height of the body centre above the isocentre, from the thickness over the topogram range."""
    lo, hi = span_mm(topo)
    top, bottom = ctx.pack.data_range_mm
    k0 = ctx.pack.slice_index(min(max(ctx.body_z(lo), top), bottom))
    k1 = ctx.pack.slice_index(min(max(ctx.body_z(hi), top), bottom))
    # The per-slice thickness may include the table under the patient and is NaN outside the body, so take the
    # median over the range rather than the mean or a single slice.
    thickness = float(np.nanmedian(ctx.pack.metrics.ap_mm[k0:k1 + 1]))
    return ctx.table.height_mm + thickness / 2.0 - ctx.spec.iso_height_mm


def _check_centring(ctx: CTContext, step: Step, height: Field) -> Generator:
    topo = next((t for t in ctx.console.topograms if t.complete), None)
    if topo is None:
        raise StepError("Acquire a topogram first")
    offset = _body_centre_offset_mm(ctx, topo)
    where = "above" if offset > 0 else "below"
    text = "on the isocentre" if abs(offset) < 0.5 else f"{abs(offset):.0f} mm {where} isocentre"
    step.add_result("Centring", f"Body centre {text}")
    new = step.value("new_height_mm")
    dual = "LAT" in ctx.protocol.topogram.views
    step.invalidates = ()
    if abs(new - ctx.table.height_mm) > 0.05:
        yield from ctx.table.move_height(new)
        step.add_result("Table height", f"Moved to {new:.0f} mm")
        if dual:
            step.add_result("Topogram", "No new topogram needed: the lateral view corrects for position "
                                        "(Siemens, research note 01 F)")
        else:
            step.invalidates = ("topogram_ap",)
            step.add_result("Topogram", "Repeat the AP topogram: the height changed and there is no lateral view")
    _sync_height(ctx, height)


def topogram_steps(ctx: CTContext) -> list[Step]:
    ap_fields, lat_fields = _fields(ctx, "AP"), _fields(ctx, "LAT")
    ap, lat = ({f.key: f for f in fields} for fields in (ap_fields, lat_fields))
    height = _height_field(ctx)

    def run(view: str):
        def routine(c: CTContext, step: Step) -> Generator:
            if view == "AP":
                _copy_values(ap, lat)
            try:
                yield from _acquire(c, step, view)
            except OutsideAnatomy as err:
                raise StepError(str(err)) from None
            _sync_height(c, height)
        return routine

    def centring(c: CTContext, step: Step) -> Generator:
        yield from _check_centring(c, step, height)

    def has_lateral(c: CTContext, step: Step) -> list[str]:
        return [] if "LAT" in c.protocol.topogram.views else ["This protocol has no lateral topogram"]

    common = "The tube stays parked while the table moves under it and the image grows row by row (note 01, A5). "
    steps = [
        _step("topogram_ap", common + "AP: tube above the patient. Dose of the topogram is not counted in the "
              "exam DLP: research gives only its effective dose (0.04 to 0.42 mSv).",
              ap_fields, run("AP"), repeatable=True, invalidates=("plan_ranges",), check=before_injection),
        _step("topogram_lat", common + "Lateral: tube on the patient's left, so the view also shows how high or "
              "low the patient lies.", lat_fields, run("LAT"), repeatable=True, invalidates=("plan_ranges",),
              check=all_of(has_lateral, before_injection)),
        _step("check_centring", "Judge how far the body centre is from the isocentre. After a height change a "
              "new AP topogram is advised, but not when a lateral one was taken (Siemens, note 01 F).",
              [height], centring, repeatable=True, check=before_injection,
              requires=() if "LAT" in ctx.protocol.topogram.views else ("topogram_ap",)),
    ]
    return steps


def _step(step_id: str, info: str, fields: list, routine, **kwargs) -> Step:
    stage_id, title, actor, place, _ = sample_step(step_id)
    return Step(step_id, stage_id, title, actor=actor, place=place, info=info, fields=fields,
                routine=routine, **kwargs)

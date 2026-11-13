"""Shared helpers for tests that drive an exam session step by step."""
from scansim.snapshot import Snapshot, StepView

PRESCAN = [
    "order_received", "protocol_assigned", "chart_check", "identify_patient", "safety_screening",
    "consent", "change_clothes", "iv_access", "breath_coaching", "register_patient", "load_injector",
    "prepare_table", "patient_on_table", "centre_patient", "connect_injector", "table_height",
    "set_landmark", "leave_room",
]


def do(session, step_id: str) -> None:
    """Perform a step, check it was accepted, and let it finish."""
    result = session.dispatch({"type": "perform", "step_id": step_id})
    assert result.ok, f"{step_id}: {result.error}"
    session.run_until_idle()


def steps(snap: Snapshot) -> dict[str, StepView]:
    return {s.id: s for stage in snap.stages for s in stage.steps}


def png_array(data: bytes):
    """Decode PNG bytes into a numpy array."""
    import io

    import numpy as np
    from PIL import Image

    return np.array(Image.open(io.BytesIO(data)))


def truth_covered(session, pack) -> bool:
    """Whether the planned non-contrast range contains the whole liver, from the snapshot alone.

    Reads the plan and the reference lines (turned on, then off again); it shares no code with the review step.
    """
    session.dispatch({"type": "set_reference", "on": True})
    snap = session.snapshot()
    session.dispatch({"type": "set_reference", "on": False})
    lines = {line.name: line.from_landmark_mm for line in snap.console.reference}
    plan = next(s for s in snap.console.series if s.id == "noncontrast").plan
    return plan.start_mm <= lines["liver_top"] and lines["liver_bottom"] <= plan.end_mm


# ---- the whole exam, in order ----

ORDER = [
    *PRESCAN,
    "topogram_ap", "topogram_lat", "check_centring", "plan_ranges", "confirm_settings", "scan_noncontrast",
    "review_noncontrast", "monitoring_slice", "place_roi", "arm_injector", "inject_and_arterial",
    "scan_venous", "scan_delayed", "review_phases", "send_images", "table_out", "disconnect_injector",
    "patient_off_table", "post_contrast_care", "room_turnaround", "close_exam",
]
ROI_OFFSET_OFF_AORTA_MM = (-80.0, -60.0)     # to the patient's right (-x) and in front (-y) of the true aorta


def _set(session, step_id: str, key: str, value) -> None:
    result = session.dispatch({"type": "set_field", "step_id": step_id, "key": key, "value": value})
    assert result.ok, f"{step_id}.{key}: {result.error}"


def aorta_in_plan_frame(session, pack) -> tuple[float, float]:
    """True aorta position at the monitoring slice, in mm from the arterial plan's field-of-view centre.

    Read from the pack's per-slice metrics, with the landmark and the plan taken from the snapshot.
    """
    snap = session.snapshot()
    landmark = steps(snap)["set_landmark"]
    z_landmark = next(f.value for f in landmark.fields if f.key == "distance_from_head_mm")
    k = pack.slice_index(z_landmark + snap.console.tracking.slice_mm)
    plan = next(s for s in snap.console.series if s.id == "arterial").plan
    return (float(pack.metrics.aorta_x_mm[k]) - plan.fov_center_x_mm,
            float(pack.metrics.aorta_y_mm[k]) - plan.fov_center_y_mm)


def _prepare(session, pack, step_id: str, roi_on_aorta: bool) -> None:
    """Edits a competent technologist makes before performing a step; every other step runs on defaults."""
    if step_id == "review_noncontrast":
        _set(session, step_id, "liver_included", "yes" if truth_covered(session, pack) else "no")
    elif step_id == "place_roi":
        x, y = aorta_in_plan_frame(session, pack)
        if not roi_on_aorta:
            x, y = x + ROI_OFFSET_OFF_AORTA_MM[0], y + ROI_OFFSET_OFF_AORTA_MM[1]
        _set(session, step_id, "roi_x_mm", x)
        _set(session, step_id, "roi_y_mm", y)


def perform_until(session, pack, last_step_id: str, *, roi_on_aorta: bool = True) -> None:
    """Run the exam in order up to and including `last_step_id`, skipping steps that are already done."""
    for step_id in ORDER[: ORDER.index(last_step_id) + 1]:
        if steps(session.snapshot())[step_id].status == "done":
            continue                      # the contrast chain runs by itself
        _prepare(session, pack, step_id, roi_on_aorta)
        do(session, step_id)


def perform_all(session, pack, *, roi_on_aorta: bool = True) -> None:
    """Run the whole exam with default values, placing the region on the true aorta (or off it) and answering
    the non-contrast review truthfully."""
    perform_until(session, pack, ORDER[-1], roi_on_aorta=roi_on_aorta)

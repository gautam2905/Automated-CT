"""Hand-built mid-exam CT snapshot used by the schema export and by client fixtures.

The exam is at the moment the injector is running and bolus tracking is monitoring.
"""
from scansim.snapshot import (
    ClockView, ConsoleView, CTScannerView, DoseView, FieldView, InjectorView, LogEntry,
    OptionView, PatientView, PoseView, ProtocolView, ReconView, ResultView, RoomView,
    SeriesPlanView, SeriesView, Snapshot, StageView, StepView, SurfaceMark, TableView,
    TopogramView, TrackingSample, TrackingView,
)

SID = "sample"
RUNNING_STEP = "inject_and_arterial"
LAST_DONE_STEP = "arm_injector"

# stage id, title, then (step id, title, actor, place, info)
_STAGES = [
    ("request", "Request", [
        ("order_received", "Order received", "radiologist", "console", "Read the exam request."),
        ("protocol_assigned", "Protocol assigned", "radiologist", "console", "Confirm the protocol matches the request."),
        ("chart_check", "Chart check", "nurse", "preparation", "Check allergies, kidney function and previous scans."),
    ]),
    ("arrival", "Arrival and screening", [
        ("identify_patient", "Identify patient", "technologist", "reception", "Check name and date of birth against the order."),
        ("safety_screening", "Safety screening", "nurse", "reception", "Ask the screening questions."),
        ("consent", "Consent", "nurse", "reception", "Explain the exam and the contrast; record consent."),
        ("change_clothes", "Change clothes", "patient", "preparation", "Remove metal and change into a gown."),
        ("iv_access", "IV access", "nurse", "preparation", "Place a cannula in a suitable vein."),
        ("breath_coaching", "Breath coaching", "technologist", "preparation", "Practise the breath-hold with the patient."),
    ]),
    ("preparation", "Preparation", [
        ("register_patient", "Register patient", "technologist", "console", "Enter the patient and the protocol at the console."),
        ("load_injector", "Load injector", "technologist", "scan_room", "Fill and purge the injector syringes."),
        ("prepare_table", "Prepare table", "technologist", "scan_room", "Cover the table and lay out supports."),
    ]),
    ("positioning", "Positioning", [
        ("patient_on_table", "Patient on table", "patient", "scan_room", "Help the patient lie supine, feet first, arms up."),
        ("centre_patient", "Centre patient", "technologist", "scan_room", "Straighten and centre the patient on the table."),
        ("connect_injector", "Connect injector", "technologist", "scan_room", "Connect the line and test-flush with saline."),
        ("table_height", "Table height", "technologist", "scan_room", "Set the table height to the isocentre."),
        ("set_landmark", "Set landmark", "technologist", "scan_room", "Put the laser on the landmark and zero the table."),
        ("leave_room", "Leave room", "technologist", "scan_room", "Leave the room and close the door."),
    ]),
    ("topogram", "Topogram", [
        ("topogram_ap", "AP topogram", "scanner", "console", "Acquire the AP topogram."),
        ("topogram_lat", "Lateral topogram", "scanner", "console", "Acquire the lateral topogram."),
        ("check_centring", "Check centring", "technologist", "console", "Check the patient is centred on both views."),
    ]),
    ("planning", "Planning", [
        ("plan_ranges", "Plan ranges", "technologist", "console", "Set the scan range for each series on the topogram."),
        ("confirm_settings", "Confirm settings", "technologist", "console", "Check kV, dose and reconstruction settings."),
    ]),
    ("noncontrast", "Non-contrast scan", [
        ("scan_noncontrast", "Scan non-contrast", "scanner", "console", "Give the breath command and scan."),
        ("review_noncontrast", "Review non-contrast", "technologist", "console", "Check the whole liver is covered."),
    ]),
    ("tracking", "Tracking set-up", [
        ("monitoring_slice", "Monitoring slice", "technologist", "console", "Scan the monitoring slice at the tracking level."),
        ("place_roi", "Place ROI", "technologist", "console", "Place the region of interest in the descending aorta."),
        ("arm_injector", "Arm injector", "technologist", "console", "Arm the injector and check the pressure limit."),
    ]),
    ("contrast", "Contrast phases", [
        ("inject_and_arterial", "Inject and arterial scan", "scanner", "console", "Start the injection and monitoring; scan on trigger."),
        ("scan_venous", "Venous scan", "scanner", "console", "Scan 55 seconds after the trigger."),
        ("scan_delayed", "Delayed scan", "scanner", "console", "Scan 4 minutes after the injection start."),
    ]),
    ("review", "Review and send", [
        ("review_phases", "Review phases", "technologist", "console", "Check each phase for coverage, motion and enhancement."),
        ("send_images", "Send images", "technologist", "console", "Send the images to the archive."),
    ]),
    ("aftercare", "Aftercare", [
        ("table_out", "Table out", "technologist", "scan_room", "Bring the table out and enter the room."),
        ("disconnect_injector", "Disconnect injector", "nurse", "scan_room", "Disconnect the line from the cannula."),
        ("patient_off_table", "Patient off table", "patient", "scan_room", "Help the patient off the table."),
        ("post_contrast_care", "Post-contrast care", "nurse", "preparation", "Check the site and give after-care advice."),
        ("room_turnaround", "Room turnaround", "technologist", "scan_room", "Clean the table and reset the room."),
        ("close_exam", "Close exam", "technologist", "console", "Complete the record."),
    ]),
]


def _num(key, label, value, source, unit="", lo=None, hi=None, step=None, help=""):
    return FieldView(key=key, label=label, type="number", value=value, default=value, unit=unit,
                     min=lo, max=hi, step=step, source=source, help=help)


# The series of the sample: (id, label). The range fields below and the series plans both use them.
_SERIES = (("noncontrast", "Non-contrast"), ("arterial", "Arterial"), ("venous", "Venous"),
           ("delayed", "4 minute delay"))


def _sample_range_fields() -> list[FieldView]:
    """The fields of `plan_ranges` with the keys the engine uses: `<series id>.start_mm` and `.end_mm`."""
    ranges = [field for sid, label in _SERIES for field in (
        _num(f"{sid}.start_mm", f"{label} start", -80, "assumption", "mm", -1500, 1500, 1,
             "From the landmark; negative is toward the head."),
        _num(f"{sid}.end_mm", f"{label} end", 320, "assumption", "mm", -1500, 1500, 1))]
    link = FieldView(key="link_ranges", label="Link ranges", type="bool", value=True, default=True,
                     source="assumption", help="While on, changing one series' start or end changes them all.")
    return [*ranges, link,
            _num("fov_mm", "Field of view", 400, "assumption", "mm", 100, 500, 1),
            _num("fov_center_x_mm", "Field of view centre x", 0, "assumption", "mm", -250, 250, 1),
            _num("fov_center_y_mm", "Field of view centre y", 20, "assumption", "mm", -250, 250, 1)]


def _sample_fields() -> dict[str, list[FieldView]]:
    gauge = FieldView(key="gauge", label="Cannula gauge", type="choice", value="20g", default="20g",
                      options=[OptionView(value="18g", label="18 gauge"), OptionView(value="20g", label="20 gauge")],
                      source="protocol", help="The protocol accepts 18g or 20g.")
    consent = FieldView(key="consent_given", label="Consent given", type="bool", value=True, default=False,
                        source="patient")
    note = FieldView(key="chart_note", label="Chart note", type="text", value="No known contrast allergy",
                     default="", source="patient", editable=True)
    return {
        "chart_check": [note],
        "consent": [consent],
        "iv_access": [gauge],
        "register_patient": [
            _num("height_cm", "Height", 172, "patient", "cm", 100, 220, 1, "Estimated at the desk."),
            _num("weight_kg", "Weight", 74, "patient", "kg", 30, 300, 1),
        ],
        "load_injector": [
            _num("contrast_ml", "Contrast volume", 125, "protocol", "mL", 20, 200, 1),
            _num("contrast_rate_ml_s", "Contrast rate", 4.0, "protocol", "mL/s", 1, 6, 0.5),
            _num("saline_ml", "Saline chaser", 40, "assumption", "mL", 0, 100, 5),
        ],
        "plan_ranges": _sample_range_fields(),
        "confirm_settings": [
            _num("kv", "Tube voltage", 120, "protocol", "kV", 70, 150, 10),
            _num("quality_ref_mas", "Quality reference", 147, "protocol", "mAs", 20, 400, 1),
            FieldView(key="ctdi_estimate_mgy", label="Estimated CTDIvol", type="number", value=11.8,
                      default=11.8, unit="mGy", source="computed", editable=False),
        ],
        "place_roi": [_num("roi_r_mm", "ROI radius", 8, "assumption", "mm", 3, 15, 1)],
    }


def _sample_results() -> dict[str, list[ResultView]]:
    return {
        "scan_noncontrast": [ResultView(label="DLP", value="467 mGy·cm")],
        "review_noncontrast": [ResultView(label="Liver covered", value="Yes")],
        "check_centring": [ResultView(label="Centring offset", value="4 mm")],
    }


def _sample_stages() -> list[StageView]:
    fields, results = _sample_fields(), _sample_results()
    stages: list[StageView] = []
    status, previous = "done", None
    for stage_id, title, steps in _STAGES:
        views = []
        for sid, stitle, actor, place, info in steps:
            this = "running" if sid == RUNNING_STEP else status
            views.append(StepView(
                id=sid, stage_id=stage_id, title=stitle, actor=actor, place=place, info=info,
                status=this, blocked_by=[previous] if this == "locked" and previous else [],
                fields=fields.get(sid, []), results=results.get(sid, []),
                repeatable=sid in ("topogram_ap", "topogram_lat", "monitoring_slice"),
            ))
            if sid == RUNNING_STEP:
                status = "locked"
            previous = sid
        stages.append(StageView(id=stage_id, title=title, steps=views))
    return stages


def _sample_series() -> list[SeriesView]:
    def plan(dlp: float) -> SeriesPlanView:
        return SeriesPlanView(
            start_mm=-80, end_mm=320, fov_mm=400, fov_center_x_mm=0, fov_center_y_mm=20, kv=120,
            quality_ref_mas=147, pitch=0.8, rotation_s=0.5, collimation_mm=57.6, feed_mm_s=92.16,
            scan_time_s=4.34, ctdi_vol_mgy=11.7, dlp_mgycm=dlp)

    def recon(plane, thick, inc, count, ready):
        return ReconView(plane=plane, thickness_mm=thick, increment_mm=inc, kernel="Br40",
                         image_count=count, ready=ready)

    def series(sid, label, status, fraction, recons, started=None):
        return SeriesView(id=sid, label=label, status=status, plan=plan(468), recons=recons,
                          image_url_template=f"/api/session/{SID}/series/{sid}/{{plane}}/{{index}}.png",
                          scanned_fraction=fraction, started_at_s=started)

    three = lambda ready: [recon("axial", 3, 1.5, 267, ready), recon("coronal", 5, 2.5, 100, ready),
                           recon("sagittal", 5, 2.5, 120, ready)]
    labels = dict(_SERIES)
    return [
        series("noncontrast", labels["noncontrast"], "done", 1.0, [recon("axial", 3, 1.5, 267, True)], 1210.0),
        series("arterial", labels["arterial"], "planned", 0.0, three(False)),
        series("venous", labels["venous"], "planned", 0.0, three(False)),
        series("delayed", labels["delayed"], "planned", 0.0, [recon("axial", 3, 1.5, 267, False)]),
    ]


def _sample_console() -> ConsoleView:
    def topogram(view, cols):
        return TopogramView(view=view, image_url=f"/api/session/{SID}/topogram/{view}.png", rows=512,
                            cols=cols, row_mm=1.0, col_mm=1.0, row0_from_landmark_mm=-120,
                            revealed_from_row=0, revealed_to_row=512, complete=True)

    times = [10.0 + 1.2 * i for i in range(8)]
    hu = [44, 45, 43, 46, 49, 58, 74, 96]
    tracking = TrackingView(
        state="monitoring", slice_mm=140, image_url=f"/api/session/{SID}/tracking.png",
        roi_x_mm=-12, roi_y_mm=38, roi_r_mm=8, threshold_hu=100, baseline_hu=45,
        samples=[TrackingSample(t_s=t, hu=h) for t, h in zip(times, hu)])
    return ConsoleView(topograms=[topogram("AP", 384), topogram("LAT", 256)], series=_sample_series(),
                       tracking=tracking, dose=DoseView(total_dlp_mgycm=1021.0, alerts=[]))


def _sample_pose() -> PoseView:
    marks = [("sternal_notch", "Sternal notch", 306), ("xiphoid", "Xiphoid process", 476),
             ("iliac_crest", "Iliac crest", 690)]
    return PoseView(
        surface_marks=[SurfaceMark(name=n, label=lb, z_body_mm=z) for n, lb, z in marks],
        stage="lying", entry="feet_first", orientation="supine", arms="up", lateral_offset_mm=3,
        yaw_deg=0.5, breath=0.0, holding=False, anchor_t_mm=120, stature_mm=1720, iv_connected=True)


def _sample_log() -> list[LogEntry]:
    lines = [
        (0, "step", "Order received."), (40, "step", "Protocol assigned: CT Multiphase Liver."),
        (300, "step", "Patient identified and screened."), (620, "step", "IV access placed, 20g."),
        (840, "step", "Injector loaded and purged."), (1010, "step", "Patient positioned, feet first."),
        (1100, "event", "Landmark set above the liver."), (1130, "event", "AP and lateral topograms acquired."),
        (1210, "step", "Non-contrast scan complete."), (1330, "event", "Monitoring slice acquired."),
        (1400, "step", "Injector armed."), (1412, "event", "Injection started, 4.0 mL/s."),
    ]
    return [LogEntry(t_s=float(t), kind=k, text=x) for t, k, x in lines]


def sample_snapshot() -> Snapshot:
    return Snapshot(
        session_id=SID, modality="CT",
        protocol=ProtocolView(
            id="ohsu.ct.multiphase_liver", title="CT Multiphase Liver", modality="CT", region="abdomen",
            status="complete",
            source_url="https://www.ohsu.edu/sites/default/files/2026-09/ct-multiphase-liver-and-ct-multiphase-liver-with-pelvis-07.02.26.pdf"),
        patient=PatientView(id="P-0001", name="Alex Sample", age=58, sex="M", height_cm=172, weight_kg=74,
                            estimated_fields=["height_cm", "weight_kg"]),
        clock=ClockView(sim_time_s=1431.6, time_scale=5.0, contrast_timer_s=19.6),
        stages=_sample_stages(), active_step_id=RUNNING_STEP, busy_text="Injecting and monitoring",
        room=RoomView(door_open=False, warning_light_on=True, lasers_on=False, technologist_at="console"),
        table=TableView(height_mm=880, long_mm=1130, long_max_mm=2000, height_min_mm=515,
                        height_max_mm=900, zero_long_mm=730, position_mm=140),
        pose=_sample_pose(),
        scanner=CTScannerView(model="SOMATOM Force", tube_angle_deg=90, rotor_rps=2.0, beam_on=True,
                              kv=120, ma=20, iso_height_mm=960, laser_z_mm=400,
                              front_clearance_mm=300, bore_diameter_mm=780),
        injector=InjectorView(state="injecting", contrast_ml=46.6, saline_ml=40, flow_ml_s=4.0,
                              pressure_psi=182, pressure_limit_psi=325, injected_contrast_ml=78.4,
                              injected_saline_ml=0),
        console=_sample_console(), log=_sample_log())

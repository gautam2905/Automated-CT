from typing import Literal, Optional, Union
from pydantic import BaseModel

Modality = Literal["CT", "MRI"]
StepStatus = Literal["locked", "ready", "running", "done", "redo"]
Actor = Literal["radiologist", "nurse", "technologist", "patient", "scanner"]
Place = Literal["reception", "preparation", "scan_room", "console"]
FieldType = Literal["number", "choice", "bool", "text"]
FieldSource = Literal["protocol", "scanner", "patient", "assumption", "computed"]
Scalar = Union[float, bool, str, None]


class OptionView(BaseModel):
    value: str
    label: str


class FieldView(BaseModel):
    key: str
    label: str
    type: FieldType
    value: Scalar
    default: Scalar
    unit: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    options: list[OptionView] = []
    source: FieldSource
    help: str = ""
    editable: bool = True


class ResultView(BaseModel):
    label: str
    value: str
    alert: bool = False


class StepView(BaseModel):
    id: str
    stage_id: str
    title: str
    actor: Actor
    place: Place
    info: str
    status: StepStatus
    blocked_by: list[str] = []
    fields: list[FieldView] = []
    results: list[ResultView] = []
    repeatable: bool = False
    action_label: str = "Do step"


class StageView(BaseModel):
    id: str
    title: str
    steps: list[StepView]


class ProtocolView(BaseModel):
    id: str
    title: str
    modality: Modality
    region: str
    status: Literal["complete", "draft"]
    source_url: str


class PatientView(BaseModel):
    id: str
    name: str
    age: int
    sex: Literal["F", "M"]
    height_cm: float
    weight_kg: float
    estimated_fields: list[str]


class ClockView(BaseModel):
    sim_time_s: float
    time_scale: float
    contrast_timer_s: Optional[float] = None   # seconds since injection start; keeps counting until the session ends


class RoomView(BaseModel):
    door_open: bool
    warning_light_on: bool
    lasers_on: bool
    technologist_at: Literal["reception", "preparation", "gantry", "console"]


class TableView(BaseModel):
    height_mm: float
    long_mm: float
    long_max_mm: float
    height_min_mm: float
    height_max_mm: float
    zero_long_mm: Optional[float] = None
    position_mm: Optional[float] = None   # from_landmark_mm of the body point in the scan plane


class SurfaceMark(BaseModel):         # a landmark that can be felt from outside; always shown
    name: str
    label: str
    z_body_mm: float


class PoseView(BaseModel):
    surface_marks: list[SurfaceMark] = []
    stage: Literal["away", "entering", "standing", "sitting", "lying", "leaving"]
    entry: Literal["head_first", "feet_first"]
    orientation: Literal["supine", "prone"]
    arms: Literal["up", "down"]
    lateral_offset_mm: float
    yaw_deg: float
    breath: float            # -1 full expiration .. +1 full inspiration
    holding: bool
    anchor_t_mm: float
    stature_mm: float
    iv_connected: bool


class CTScannerView(BaseModel):
    kind: Literal["CT"] = "CT"
    model: str
    tube_angle_deg: float
    rotor_rps: float
    beam_on: bool
    kv: int
    ma: float
    iso_height_mm: float
    laser_z_mm: float
    front_clearance_mm: float
    bore_diameter_mm: float


class InjectorView(BaseModel):
    state: Literal["unloaded", "loaded", "purged", "connected", "armed", "injecting", "done"]
    contrast_ml: float
    saline_ml: float
    flow_ml_s: float
    pressure_psi: float
    pressure_limit_psi: float
    injected_contrast_ml: float
    injected_saline_ml: float


class TopogramView(BaseModel):
    view: Literal["AP", "LAT"]
    image_url: str
    rows: int
    cols: int
    row_mm: float
    col_mm: float
    row0_from_landmark_mm: float     # planning coordinate of image row 0
    revealed_from_row: int
    revealed_to_row: int             # exclusive; equal to revealed_from_row before acquisition
    complete: bool


class ReconView(BaseModel):
    plane: Literal["axial", "coronal", "sagittal"]
    thickness_mm: float
    increment_mm: float
    kernel: str
    image_count: int
    ready: bool


class SeriesPlanView(BaseModel):
    start_mm: float
    end_mm: float
    fov_mm: float
    fov_center_x_mm: float
    fov_center_y_mm: float
    kv: int
    quality_ref_mas: float
    pitch: float
    rotation_s: float
    collimation_mm: float
    feed_mm_s: float
    scan_time_s: float
    ctdi_vol_mgy: float
    dlp_mgycm: float


class SeriesView(BaseModel):
    id: str
    label: str
    status: Literal["planned", "scanning", "done", "missed"]
    plan: SeriesPlanView
    recons: list[ReconView]
    image_url_template: str          # contains {plane} and {index}
    scanned_fraction: float
    started_at_s: Optional[float] = None
    motion: bool = False


class TrackingSample(BaseModel):
    t_s: float                       # seconds since injection start
    hu: float


class TrackingView(BaseModel):
    state: Literal["idle", "slice_acquired", "monitoring", "triggered", "manual", "missed"]
    slice_mm: Optional[float] = None
    image_url: Optional[str] = None
    roi_x_mm: float
    roi_y_mm: float
    roi_r_mm: float
    threshold_hu: float              # rise above baseline that triggers
    baseline_hu: Optional[float] = None
    samples: list[TrackingSample] = []
    triggered_at_s: Optional[float] = None   # simulation time


class DoseView(BaseModel):
    total_dlp_mgycm: float
    alerts: list[str] = []


class ReferenceLine(BaseModel):
    name: str
    label: str
    from_landmark_mm: float


class ReferencePoint(BaseModel):      # a true position on the tracking image, in mm from the field-of-view centre
    name: str
    label: str
    x_mm: float
    y_mm: float


class ConsoleView(BaseModel):
    topograms: list[TopogramView] = []
    series: list[SeriesView] = []
    tracking: Optional[TrackingView] = None
    dose: DoseView
    reference: list[ReferenceLine] = []      # empty unless show_reference
    reference_points: list[ReferencePoint] = []   # empty unless show_reference and the monitoring slice exists


class LogEntry(BaseModel):
    t_s: float
    kind: Literal["step", "event", "voice", "alert"]
    text: str


class Snapshot(BaseModel):
    version: int = 1
    session_id: str
    modality: Modality
    protocol: ProtocolView
    patient: PatientView
    clock: ClockView
    stages: list[StageView]
    active_step_id: Optional[str] = None
    busy_text: Optional[str] = None
    room: RoomView
    table: TableView
    pose: PoseView
    scanner: CTScannerView
    injector: Optional[InjectorView] = None
    console: ConsoleView
    log: list[LogEntry] = []
    show_reference: bool = False

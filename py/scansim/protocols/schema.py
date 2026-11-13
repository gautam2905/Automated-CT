from typing import Literal, Optional

from pydantic import BaseModel


class Source(BaseModel):
    organisation: str
    url: str
    reviewed: str
    local_file: Optional[str] = None


class Positioning(BaseModel):
    orientation: Literal["supine", "prone"]
    entry: Literal["head_first", "feet_first"]
    arms: Literal["up", "down"]
    laser_landmark: str
    landmark_fraction_of_height: float            # distance from vertex / stature, for the pre-filled estimate


class TopogramSpec(BaseModel):
    views: list[Literal["AP", "LAT"]]
    direction: Literal["craniocaudal", "caudocranial"]
    coverage_text: str
    start_from_landmark_mm: float
    length_mm: float
    kv: int
    ma: float


class ContrastTiming(BaseModel):
    method: Literal["none", "bolus_tracking", "fixed_delay"]
    roi_text: str = ""
    level_text: str = ""
    threshold_hu: float = 0
    monitoring_delay_s: float = 0
    monitoring_interval_s: float = 0
    max_monitoring_s: float = 0
    post_trigger_delay_s: float = 0


class ContrastSpec(BaseModel):
    agent: str
    concentration_mgi_ml: float
    volume_ml: float
    rate_ml_s: float
    saline_ml: float
    saline_rate_ml_s: float
    iv_gauges: list[str]
    timing: ContrastTiming


class SeriesTiming(BaseModel):
    type: Literal["no_contrast", "before_contrast", "at_trigger", "after_trigger", "after_injection_start"]
    delay_s: float = 0


class ReconSpec(BaseModel):
    plane: Literal["axial", "coronal", "sagittal"]
    thickness_mm: float
    increment_mm: float
    kernel: str


class SeriesSpec(BaseModel):
    id: str
    label: str
    coverage_text: str
    default_start_mm: float
    default_end_mm: float   # from_landmark_mm
    timing: SeriesTiming
    breath_hold: Literal["inspiration", "expiration", "none"]
    recons: list[ReconSpec]


class ScanDefaults(BaseModel):
    kv: int
    quality_ref_mas: float
    pitch: float
    rotation_s: float
    collimation_mm: float
    fov_mm: float
    iterative: str


class CTProtocol(BaseModel):
    id: str
    modality: Literal["CT"]
    title: str
    region: str
    status: Literal["complete", "draft"]
    source: Source
    indication: str
    positioning: Positioning
    preparation: list[str]
    topogram: TopogramSpec
    contrast: Optional[ContrastSpec]
    series: list[SeriesSpec]
    scan_defaults: ScanDefaults
    review_checks: list[str]
    notes: list[str] = []
    quotes: dict[str, str]          # dotted field path -> verbatim sheet text
    assumptions: dict[str, str]     # dotted field path -> why this value, with URL if any

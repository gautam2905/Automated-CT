from pathlib import Path

from pydantic import BaseModel


class TableSpec(BaseModel):
    height_min_mm: float
    height_max_mm: float
    height_min_in_bore_mm: float
    long_max_mm: float
    long_speed_mm_s: float
    vertical_speed_mm_s: float
    max_load_kg: float
    length_mm: float
    feet_first_anchor_mm: float
    head_first_anchor_mm: float


class TopogramOptions(BaseModel):
    lengths_mm: list[float]
    speed_mm_s: float
    kv_options: list[int]
    default_ma: float


class CTScannerSpec(BaseModel):
    id: str
    vendor: str
    model: str
    bore_diameter_mm: float
    iso_height_mm: float
    front_clearance_mm: float
    laser_z_mm: float
    table: TableSpec
    kv_options: list[int]
    rotation_times_s: list[float]
    collimations_mm: list[float]
    max_pitch: float
    topogram: TopogramOptions
    ctdi_mgy_per_100mas: dict[str, float]
    reference_dw_mm: float
    modulation_strength: float
    dose_notification_ctdi_mgy: float
    dose_alert_ctdi_mgy: float
    recon_images_per_s: float
    rotor_spinup_s: float
    sources: dict[str, str]
    assumptions: dict[str, str]


def load_scanner(path: Path) -> CTScannerSpec:
    return CTScannerSpec.model_validate_json(Path(path).read_text(encoding="utf-8"))

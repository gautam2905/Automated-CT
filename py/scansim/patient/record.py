"""Patient record: a synthetic identity plus body size taken from the scan, and the clinical
answers the screening steps use.

Assumptions (every number below that is not read from the pack):
- Age (25 to 75) and sex are drawn from a generator seeded with the exam seed and the patient id
  (``variation_seed``), so two patients differ under the same seed. They are not in the scan data,
  so they are listed in ``estimated_fields`` together with height and weight, which are estimated
  from the CT.
- eGFR 90 mL/min/1.73 m2, no prior contrast reaction, no metformin, 20 g IV cannula.
- ``max_hold_s`` = 25 s: no sourced breath-hold limit exists for CT.
- Cardiac output: research note 02 section D found no patient-specific formula with sourced
  constants (only the 6.5 L/min standard adult, Sahbaee 2016). The record therefore uses
  6.5 L/min scaled by body surface area over 1.9 m2, with body surface area from the Mosteller
  formula sqrt(height_cm * weight_kg / 3600). The scaling and 1.9 m2 are assumptions.
"""
from __future__ import annotations

import math
import re
import zlib
from dataclasses import dataclass, field

import numpy as np

from scansim.patient.pack import PatientPack
from scansim.snapshot import PatientView

AGE_MIN, AGE_MAX = 25, 75
REFERENCE_CARDIAC_OUTPUT_L_MIN = 6.5
REFERENCE_BSA_M2 = 1.9
DEFAULT_EGFR = 90
DEFAULT_IV_GAUGE = "20g"
DEFAULT_MAX_HOLD_S = 25.0


@dataclass
class PatientRecord:
    id: str
    name: str
    age: int
    sex: str
    height_cm: float
    weight_kg: float
    egfr: float
    prior_contrast_reaction: bool
    on_metformin: bool
    pregnancy: str
    iv_gauge: str
    estimated_fields: list[str] = field(default_factory=list)
    cardiac_output_l_min: float = REFERENCE_CARDIAC_OUTPUT_L_MIN
    max_hold_s: float = DEFAULT_MAX_HOLD_S

    def view(self) -> PatientView:
        return PatientView(
            id=self.id, name=self.name, age=self.age, sex=self.sex,
            height_cm=self.height_cm, weight_kg=self.weight_kg,
            estimated_fields=list(self.estimated_fields),
        )


def body_surface_area_m2(height_cm: float, weight_kg: float) -> float:
    """Mosteller body surface area."""
    return math.sqrt(height_cm * weight_kg / 3600.0)


RECORD_STREAM, SETUP_STREAM = 0, 1


def variation_seed(patient_id: str, seed: int, stream: int) -> list[int]:
    """Seed for one stream of a patient's seeded variation: the exam seed, the stream and the patient id
    (as a checksum, which is the same in every run, unlike Python's `hash`)."""
    return [seed, stream, zlib.crc32(patient_id.encode("utf-8"))]


def make_record(pack: PatientPack, seed: int) -> PatientRecord:
    rng = np.random.default_rng(variation_seed(pack.id, seed, RECORD_STREAM))
    age = int(rng.integers(AGE_MIN, AGE_MAX + 1))
    sex = "F" if rng.integers(0, 2) == 0 else "M"
    height_cm = pack.stature_mm / 10.0
    weight_kg = float(pack.weight_kg)
    bsa = body_surface_area_m2(height_cm, weight_kg)
    return PatientRecord(
        id=pack.id,
        name="Volunteer " + "".join(re.findall(r"\d", pack.id)),
        age=age,
        sex=sex,
        height_cm=height_cm,
        weight_kg=weight_kg,
        egfr=DEFAULT_EGFR,
        prior_contrast_reaction=False,
        on_metformin=False,
        pregnancy="not applicable" if sex == "M" else "no",
        iv_gauge=DEFAULT_IV_GAUGE,
        estimated_fields=["age", "sex", "height_cm", "weight_kg"],
        cardiac_output_l_min=REFERENCE_CARDIAC_OUTPUT_L_MIN * bsa / REFERENCE_BSA_M2,
        max_hold_s=DEFAULT_MAX_HOLD_S,
    )

"""The pre-filled fields of the first eighteen steps; the steps themselves are in workflow_prescan.py.

A field's `source` says where its pre-filled value comes from, and the page shows it as a tag. `assumption`
(shown as "assumed") marks every value that is not sourced: a value the protocol or the scanner file lists
among its assumptions, a clinical answer of the synthetic patient record, and every simulator default.

ASSUMPTIONS made here, each said in the field's `help`:
  - INJECTOR_OVERFILL_ML: 5 mL of contrast drawn up beyond the protocol volume, for priming;
  - TEST_VOLUME_ML: a 10 mL saline test flush;
  - TABLE_HEIGHT_BELOW_ISO_MM: the tabletop 110 mm below the isocentre for an average build;
  - the 200 mL syringe sizes, the height limits of 100 to 220 cm and the weight minimum of 30 kg.
"""
from scansim.core.fields import Field
from scansim.ct.context import CTContext, ReadOnlyField
from scansim.ct.scan_fields import number_field, scanner_source

INJECTOR_OVERFILL_ML = 5.0
TEST_VOLUME_ML = 10.0
MIN_PHASE_ML = 0.1            # the smallest volume an injector phase can be programmed with
SYRINGE_ML = 200.0
TABLE_HEIGHT_BELOW_ISO_MM = 110.0
SYNTHETIC = "The patient record is synthetic, so this answer is assumed."
IV_SITES = (("antecubital_right", "Antecubital, right"), ("antecubital_left", "Antecubital, left"),
            ("forearm", "Forearm"), ("hand", "Hand"))
POSITIONS = {
    "feet_first_supine": ("feet_first", "supine", "Feet first, supine"),
    "head_first_supine": ("head_first", "supine", "Head first, supine"),
    "feet_first_prone": ("feet_first", "prone", "Feet first, prone"),
    "head_first_prone": ("head_first", "prone", "Head first, prone"),
}


def flag(key, label, value, source, help=""):
    return Field(key, label, "bool", value, source=source, help=help)


def choice(key, label, value, source, options, help=""):
    return Field(key, label, "choice", value, source=source, options=options, help=help)


def saline_needed_ml(ctx: CTContext) -> float:
    """Saline the exam needs from the syringe: the protocol's chaser and the test flush."""
    contrast = ctx.protocol.contrast
    return (contrast.saline_ml if contrast else 0.0) + TEST_VOLUME_ML


def chart_fields(ctx: CTContext) -> list[Field]:
    rec = ctx.record
    return [
        number_field("egfr", "eGFR", rec.egfr, "assumption", unit="mL/min/1.73 m2", lo=0, hi=200,
                     help=f"Most recent result on the chart. Under 30 raises an alert. {SYNTHETIC}"),
        flag("prior_reaction", "Prior contrast reaction", rec.prior_contrast_reaction, "assumption", SYNTHETIC),
        flag("on_metformin", "Takes metformin", rec.on_metformin, "assumption", SYNTHETIC),
    ]


def screening_fields(ctx: CTContext) -> list[Field]:
    return [
        choice("pregnancy", "Pregnancy", ctx.record.pregnancy, "assumption",
               [("no", "No"), ("yes", "Yes"), ("not applicable", "Not applicable")], help=SYNTHETIC),
        flag("allergy", "Allergy reported", False, "assumption",
             "The record holds no allergy history; this assumes none is reported."),
    ]


def register_fields(ctx: CTContext) -> list[Field]:
    rec, pos = ctx.record, ctx.protocol.positioning
    options = [(key, label) for key, (_, _, label) in POSITIONS.items()]
    return [
        number_field("weight_kg", "Weight", round(rec.weight_kg, 1), "patient", unit="kg", lo=30,
                     hi=ctx.spec.table.max_load_kg,
                     help="Estimated from the scan; weigh the patient if you can. The upper limit is the table's load."),
        number_field("height_cm", "Height", round(rec.height_cm, 1), "patient", unit="cm", lo=100, hi=220,
                     help="Estimated from the scan; measure if you can. The limits are an assumption."),
        choice("patient_position", "Patient position", f"{pos.entry}_{pos.orientation}", "protocol", options),
    ]


def injector_fields(ctx: CTContext) -> list[Field]:
    c = ctx.protocol.contrast
    return [
        number_field("contrast_ml", "Contrast volume", (c.volume_ml + INJECTOR_OVERFILL_ML) if c else 0.0,
                     "assumption", unit="mL", lo=0, hi=SYRINGE_ML,
                     help=f"The protocol volume plus {INJECTOR_OVERFILL_ML:g} mL for priming (assumed). An empty "
                          f"syringe is refused. The {SYRINGE_ML:g} mL syringe limit is an assumption."),
        number_field("saline_ml", "Saline", saline_needed_ml(ctx) if c else 0.0, "assumption", unit="mL",
                     lo=0, hi=SYRINGE_ML,
                     help=f"The protocol chaser plus the {TEST_VOLUME_ML:g} mL test flush, which uses saline from "
                          f"the same syringe; less than that is refused. The {SYRINGE_ML:g} mL syringe limit is an "
                          "assumption."),
        flag("purged", "Air purged", True, "assumption", "Assumes the technologist purges the lines."),
    ]


def iv_fields(ctx: CTContext) -> list[Field]:
    return [
        choice("gauge", "Cannula gauge", ctx.record.iv_gauge, "assumption",
               [("18g", "18 gauge"), ("20g", "20 gauge"), ("22g", "22 gauge")],
               help=f"The gauge placed in the patient; the protocol accepts 18g or 20g. {SYNTHETIC}"),
        choice("site", "Site", "antecubital_right", "assumption", IV_SITES,
               help="Assumes the preferred antecubital vein (ACR Manual on Contrast Media)."),
        flag("flush_ok", "Flushes without resistance", True, "assumption", "Assumes the cannula is patent."),
    ]


def _height_limits_note(ctx: CTContext) -> str:
    assumed = scanner_source(ctx.spec, "table.height_min_mm") == "assumption"
    return " The height limits are assumed: they come from a related scanner." if assumed else ""


def table_fields(ctx: CTContext) -> list[Field]:
    t = ctx.spec.table
    return [
        number_field("loading_height_mm", "Loading height", t.height_min_mm,
                     scanner_source(ctx.spec, "table.height_min_mm"), unit="mm", lo=t.height_min_mm,
                     hi=t.height_max_mm,
                     help="The lowest table height the scanner allows." + _height_limits_note(ctx)),
        flag("arm_support", "Arm support fitted", True, "assumption", "Assumes the supports are laid out."),
        flag("knee_support", "Knee support fitted", True, "assumption", "Assumes the supports are laid out."),
    ]


def landmark_fields(ctx: CTContext) -> list[Field]:
    pos, stature = ctx.protocol.positioning, ctx.pack.stature_mm
    return [
        ReadOnlyField("landmark", "Landmark", "text", pos.laser_landmark, source="protocol"),
        number_field("distance_from_head_mm", "Distance from top of head",
                     round(pos.landmark_fraction_of_height * stature), "assumption", unit="mm", lo=0, hi=stature,
                     help=f"A proportion estimate ({pos.landmark_fraction_of_height:g} of the patient's height), "
                          "not where the anatomy is; feel for the surface landmarks and adjust."),
    ]


def positioning_fields(ctx: CTContext) -> dict[str, list[Field]]:
    t, iso = ctx.spec.table, ctx.spec.iso_height_mm
    return {
        "patient_on_table": [choice("arms", "Arms", ctx.protocol.positioning.arms, "protocol",
                                    [("up", "Above the head"), ("down", "By the side")])],
        "connect_injector": [number_field(
            "test_volume_ml", "Test injection", TEST_VOLUME_ML, "assumption", unit="mL", lo=1,
            hi=ctx.protocol.contrast.saline_ml if ctx.protocol.contrast else 1.0,
            help="Saline test flush; the 10 mL volume is an assumption.")],
        "table_height": [number_field(
            "height_mm", "Table height", iso - TABLE_HEIGHT_BELOW_ISO_MM, "assumption", unit="mm",
            lo=t.height_min_mm, hi=t.height_max_mm,
            help=f"Assumes the tabletop sits {TABLE_HEIGHT_BELOW_ISO_MM:g} mm below the isocentre "
                 f"({iso:g} mm), which puts the patient's mid-line near it. Below "
                 f"{t.height_min_in_bore_mm:g} mm the table cannot enter the bore." + _height_limits_note(ctx))],
        "set_landmark": landmark_fields(ctx),
    }

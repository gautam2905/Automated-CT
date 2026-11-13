# Scan room simulator

A step-by-step simulator of a CT examination, built so that each thing a radiographer does in a real exam is a separate, visible step. The first exam is a multiphase liver CT on a Siemens SOMATOM Force, run on real CT volumes from the dataset. The aim is to see the whole procedure before automating any part of it. Nothing here is automated yet: you do every step by hand.

It is a web page (React and three.js) talking over a WebSocket to a Python engine. The engine runs on a simulated clock, shows real images of the patient (topograms, the bolus-tracking slice, slices of each scan series) and checks what you do (for example, a scan range that goes past the table is refused with the limit stated).

## Start it

Needs Python with aiohttp, numpy, scipy, pillow and pydantic 2 (on the original machine this is the `ctm` conda environment, `/mnt/miniconda3/envs/ctm`), Node 20, a built client, and at least one patient pack in `data/patients/` (see "Add a patient"; packs are not in the repository).

    cd client && npm install && npm run build && cd ..   # once, and after any client change
    ./run_sim.sh                                          # then open http://127.0.0.1:8770/
    ./run_sim.sh --port 8800                              # another port

The launcher prints the address and refuses to start if `client/dist` has not been built. It listens on 127.0.0.1 only. It uses the `ctm` environment when that exists and `python3` otherwise; set `SIM_PYTHON` to use another interpreter.

If the computer has no graphics card, the 3D room is drawn in software and the page becomes very slow. Open `http://127.0.0.1:8770/?lowgfx` instead: it draws the room at a reduced resolution, so the room looks blurry, without shadows or smoothing, and only every two seconds. Everything else is the same.

## Run an exam

1. Top bar: choose Modality CT, Exam "CT Multiphase Liver" and a Patient, then press Start exam. The Seed (1 unless you change it) sets the seeded variation: how far off-centre the patient lies down, and the synthetic age and sex. The same seed and patient give the same exam. Set Speed to 20x if you do not want to wait for real-time durations. Reset, at the far end of the bar, throws the exam away (sessions are not saved); once any step is done it asks first.
2. In the left column, open a stage and press the button on each step, in order. A step that cannot run yet says what it is waiting for. Values are pre-filled and editable, and each carries a tag that says where it comes from (see "What is real and what is assumed"). A value that is out of range is refused with a message and nothing changes. A finished step that may be repeated shows "Do again": change its values and press it. Doing a step again sends the steps that depended on it back to "Do again" as well. Once the injection has started, nothing before it can be done again, and the step says why. Stop ends a running step; a scan stopped part-way adds the part already delivered to the dose total. To give the room more space, put a side away with the handle between it and the room: the steps on the left, the console on the right. The same handle brings it back, and nothing in it is lost.
3. After the topograms, plan the scan ranges. On the Images tab the AP topogram shows the range the "Plan ranges" step holds as a dashed box. Drag its top or bottom edge, or type the numbers on the step, then press the step's button to accept: the box turns solid. While "Link ranges" is on, the four series share one range and one box. To change an accepted range, drag or type again (the new range is drawn dashed beside the accepted one) and press "Do again". Then confirm the settings, scan the non-contrast phase and answer the review question (does the range cover the whole liver?).
4. Bolus tracking. The dashed line on the AP topogram is the monitoring level, pre-filled with the middle of the arterial range; drag it or type a level, then take the monitoring slice. Then place the tracking region on the aorta. Tip: on the Images tab switch on "Show reference anatomy", then on the Contrast tab click the aorta marker on the tracking image. The click sets the region's values and draws a dashed circle there; do the step "Place ROI" to accept it and measure its baseline (the circle turns solid). A region on tissue that does not enhance never triggers. A region on another organ that enhances, such as a kidney or the spleen, can still trigger, later than the aorta would. "Start scan manually" works while monitoring runs. With the pre-filled timing, monitoring stops about 57 s after the injection starts, in time for the venous scan to start at 70 s, and the arterial phase is then lost.
5. Arm the injector and do the step "Inject and arterial scan". The venous and delayed scans start by themselves at their set times. Then review the phases, send the images, and finish the aftercare steps. The Contrast tab shows injector pressure and the tracking curve; the Dose tab shows predicted and delivered dose; the Log tab lists events.

## What is real and what is assumed

This section is written from the data files (`data/protocols/ct/ohsu_ct_multiphase_liver.json`, `data/scanners/siemens_somatom_force.json`) and from the docstrings of the engine modules, which list their own assumptions.

Real, with a source:

- The patient's anatomy. The CT volumes and organ labels are those of healthy volunteers from the Multimodal-HC dataset (DEPICT-RH/Multimodal-HC on Hugging Face, CC BY 4.0). Slices, reformats and the tracking image are drawn from these volumes, the topograms are prepared images of the same volunteers (see "Add a patient"), and the liver, the aorta and the reference marks are where the labels put them.
- What the OHSU protocol sheet states. The protocol file quotes the sheet under `quotes`: supine, feet first, arms up; landmark above the liver; 125 mL of "OMNI 350" contrast at 4 mL/s through an 18g or 20g cannula; bolus tracking on the descending aorta; the non-contrast, arterial, venous and 4-minute delayed series, with venous 55 s after the tracker and delayed 4 minutes after the injection start; inspiration breath-hold; 3 mm axial and 5 mm coronal reconstructions; reference 120 kV and quality reference 147 mAs.
- Of the SOMATOM Force itself, only what `sources` in the scanner file lists: the 780 mm bore, the 307 kg table load, the kV steps, the 57.6 mm collimation and the maximum pitch of 3.2. The dose notification (50 mGy) and alert (1000 mGy) values are sourced too, but they are the AAPM's, not the scanner's.

Assumed:

- The scanner's geometry and motion. Most of it is a proxy from a related Siemens system (the SOMATOM go.Top: table height range, table travel, table speeds, topogram lengths) or a placeholder (isocentre height, distance from the laser to the scan plane, front clearance, lowest table height inside the bore, tabletop length, rotation times, rotor spin-up, reconstruction speed). The dose calibration (CTDIvol per 100 mAs, reference diameter, strength of the tube-current adaptation) is assumed as well. Every one of these is listed under `assumptions` in the scanner file, with where the number comes from.
- Protocol values the sheet does not give, listed under `assumptions` in the protocol file: that "OMNI 350" is Omnipaque 350 with 350 mg of iodine per mL; the topogram's start, length, kV and mA; the 40 mL saline chaser and its rate; the 100 HU tracking threshold, the 10 s monitoring delay, the 1.2 s interval, the 60 s monitoring limit and the 15 s post-trigger delay; the landmark at 27 percent of the patient's height; the default scan box of -80 to 320 mm; pitch, rotation time, field of view and kernel.
- The patient record. Name, age and sex are synthetic (age and sex are drawn from the seed and the patient id), and the clinical answers are assumed: eGFR 90, no prior reaction, no metformin, not pregnant, a 20g cannula that flushes. Height and weight are estimated from the CT. Cardiac output is 6.5 L/min scaled by body surface area.
- Simulator defaults, stated in the modules that use them: how long every step takes; a set-up error of up to 25 mm and 3 degrees when the patient lies down; a 25 s breath-hold limit; 5 mL of contrast drawn up for priming, a 10 mL saline test flush and 200 mL syringes; the tabletop 110 mm below the isocentre; the pre-filled tracking region; 120 kV and 20 mAs for a monitoring scan; 20 to 90 HU as "blood" for the baseline warning; a venous scan 70 s after the injection start when nothing triggered; 15 minutes of observation.
- The models of contrast enhancement, dose and injector pressure. They are simple and have not been validated (see "Known limits").
- The step lists. They come from published material, not from watching a technologist; the design asks a CT technologist to check them.

How the page marks it:

- Every pre-filled value on a step has a tag: `protocol` (stated by the sheet), `patient` (estimated from this patient's CT), `computed`, or `assumed`. A value is tagged `assumed` when the protocol file or the scanner file lists it under `assumptions`, when it is a clinical answer of the synthetic record, and when it is a simulator default. A `scanner` tag exists for sourced scanner numbers, but no pre-filled value uses it today: every scanner number that is pre-filled is a proxy, so it reads `assumed`.
- Outside the steps: age and sex read "assumed: the record is synthetic"; height and weight read "estimated"; the injector pressure and its limit are labelled "assumed" on the Contrast tab and in the step results that quote them; the Dose total is labelled "assumed" and a line under it says what it leaves out; the step that predicts the dose says its figures are estimates.
- Not marked number by number: how long steps take, the set-up error, and what the contrast model produces (the tracking curve, the enhancement in the images and the HU figures of the phase review). These are assumptions too, and this section and "Known limits" are where they are stated.

## Add a patient

Patient packs are not in the repository: they are large and derived from the dataset. The tests need `sub-000` and `sub-001` by name and at least five packs in all; the original machine has `sub-000`, `sub-001`, `sub-002`, `sub-004` and `sub-005`. To build one from the dataset (read-only):

    PYTHONPATH=/mnt/CT_SCAN/work/python-libs:py /mnt/miniconda3/envs/ctm/bin/python tools/build_patient_pack.py --subject sub-006

It writes `data/patients/sub-006/`. Reload the page and the patient appears in the dropdown. Use an id the dataset has: there is no `sub-003`. Only `tools/build_patient_pack.py` needs `nibabel`.

The dataset folder is `/mnt/CT_SCAN/DATASET` unless `--dataset` names another. The tool reads two things from it: the volunteer's low-dose CT, organ labels and label table in `source_cache/multimodal_hc/<subject>/`, and the prepared topograms in `short_abdominal_v1/` (`arrays/<subject>_AP.npy` and `_LATERAL.npy`, with their `geometry/` files). The prepared topograms are not part of Multimodal-HC and are not made by this repository, so a copy of that folder is needed as well as the dataset. The tool accepts only plain subject names (letters, digits, `_` and `-`), refuses an `--out` inside the dataset, and replaces an existing folder only if it is a pack.

## Run the tests

    cd py && /mnt/miniconda3/envs/ctm/bin/python -m pytest -q    # engine and server
    cd client && npm test                                         # client unit tests
    cd client && npm run build                                    # type check and build
    cd client && npm run e2e                                      # browser tests

The engine tests and the browser tests need the packs named above. One engine test compares the protocol file with the text of the OHSU sheet and reads it from the path at the top of `py/tests/test_contracts.py`.

The browser tests start their own server on port 8791 (through `run_sim.sh`, so `SIM_PYTHON` applies) and drive Google Chrome (headless, through Playwright; no browser download). To use another Chrome or Chromium, set `SIM_CHROME` to its path. They open the app with `?lowgfx` only, so the normal graphics mode is not covered by them. One test performs the whole exam through the interface and writes screenshots to `client/e2e/screens/`; it takes one to three minutes, depending on the computer.

## Known limits

- CT only. MRI is listed in the dropdown but disabled. The MRI data and design are in the research notes.
- One exam: multiphase liver. Another exam needs code as well as a protocol file: the step list, the four series and the bolus-tracking flow are written for this exam in `py/scansim/ct/`. A new file in `data/protocols/` only changes values.
- The source scans were head first with the arms down, so slices show arms beside the body even though the simulated positioning puts them up.
- The 3D models are built in code. No downloaded models are installed; each download needs your approval (see the open items in the design).
- One simulated session per browser tab; sessions are not saved.
- Needs Node 20 (Vite 6, Vitest 4).
- Without a graphics card the 3D view is slow. `?lowgfx` makes the page usable but the room looks blurry, and it is the only mode the browser tests cover.
- The contrast model is a simple response per compartment (aorta, portal vein, liver, veins, kidney, spleen, pancreas, heart, other soft tissue): the iodine delivery rate is passed through a fixed transit curve and scaled for weight and cardiac output. Most of its constants are fitted, not sourced, and it has not been validated. In the images the enhancement is added as one HU value to every voxel of an organ label at the moment that image was scanned. Tissue without a label that maps to a compartment (muscle, fat, bone, lung, small vessels) does not enhance, there is no structure inside an organ, and the volunteers are healthy, so there is no lesion to see.
- The late part of the contrast curve is not physical, and it has not been retuned (the owner decides). For a 75 kg patient and the pre-filled injection, the aorta falls to about 36 HU one minute after the injection starts and then rises again to about 74 HU, where it stays for the rest of the exam. The liver peaks at about 57 HU at 70 s and is back to about 7 HU from 2.5 minutes on, so the 4-minute delayed images show almost no liver enhancement. The portal-vein and liver peaks (about 65 s and 70 s) come earlier than the roughly 102 s portal peak of the clinical series in the research notes. Every curve drops to zero 30 minutes after the injection.
- The dose figures are a model estimate with an assumed calibration. The total adds every scan series. A scan that was stopped part-way or scanned again keeps what it delivered in the total and has a row of its own on the Dose tab, so the rows add up to the total. It leaves out the topograms, the monitoring slice and the bolus-monitoring scans.
- The injector pressure is `k x rate^2 x viscosity`, with one `k` per cannula gauge and one viscosity each for contrast and saline. None of these constants is sourced, and neither is the 325 psi limit. The model ignores temperature, concentration and tubing. A test injection takes saline from the syringe but is not counted as injected saline, and a stopped injection ends in the state "done".
- With no trigger and no manual start, waiting for the trigger ends when the venous scan has to be prepared: about 57 s after the injection starts with the pre-filled timing, 13 s before monitoring's own limit. The arterial phase is then lost, the venous scan starts 70 s after the injection start (an assumption) and the delayed scan at 4 minutes. A manual start is possible only until that moment.
- Once the injection has started, no earlier step can be done again. After a stopped injection the step "Inject and arterial scan" stays undone; the venous scan is then started by hand and the exam can still be finished.
- Open defect: an injection programmed at a very low rate (for example 0.1 mL/s) can still be running when the line is disconnected and the exam is closed. Nothing stops it or refuses the disconnection.

## Where things are

- `data/protocols/ct/` protocol JSON; `data/scanners/` scanner JSON; `data/patients/` patient packs (not in the repository).
- `py/scansim/` the engine; `py/scansim_server/` the HTTP and WebSocket server; `py/tests/` their tests.
- `client/src/` the web client; `client/e2e/` the browser tests.
- `tools/build_patient_pack.py` builds patient packs.
- Research notes (on the original machine, not in the repository): `/mnt/CT_SCAN/docs/research/scan-room-sim/` (CT workflow, contrast, MRI workflow, MRI protocols, 3D models and prior art).
- Design (on the original machine, not in the repository): `/mnt/CT_SCAN/docs/superpowers/specs/2026-11-13-scan-room-simulator-design.md`.

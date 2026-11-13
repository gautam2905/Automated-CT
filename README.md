# Scan room simulator

A step-by-step simulator of a CT examination, built so that each thing a radiographer does in a real exam is a separate, visible step. The first exam is a multiphase liver CT on a Siemens SOMATOM Force, run on real CT volumes from the dataset. The aim is to see the whole procedure before automating any part of it. Nothing here is automated yet: you do every step by hand.

It is a web page (React and three.js) talking over a WebSocket to a Python engine. The engine runs on a simulated clock, produces real images from the patient volumes (topograms, bolus-tracking slice, slices of each scan series) and checks what you do (for example, a scan range that goes past the table is refused with the limit stated).

## Start it

Needs the `ctm` conda environment (`/mnt/miniconda3/envs/ctm`) and a built client.

    cd client && npm install && npm run build && cd ..   # once, and after any client change
    ./run_sim.sh                                          # then open http://127.0.0.1:8770/
    ./run_sim.sh --port 8800                              # another port

The launcher prints the address and refuses to start if `client/dist` has not been built. It listens on 127.0.0.1 only. Set `SIM_PYTHON` to use another interpreter.

If the computer has no graphics card, the 3D room is drawn in software and the page becomes very slow. Open `http://127.0.0.1:8770/?lowgfx` instead: it draws the room smaller, without shadows, and only every two seconds. Everything else is the same.

## Run an exam

1. Top bar: choose Modality CT, Exam "CT Multiphase Liver", a Patient, then press Start exam. Set Speed to 20x if you do not want to wait for real-time durations.
2. In the left column, open a stage and press the button on each step, in order. A step that cannot run yet says what it is waiting for. Values are pre-filled and editable (each carries a tag: protocol, scanner, patient, or assumed). A value that is out of range is refused with a message and nothing changes.
3. After the topograms, plan the three scan ranges on the Images tab (drag the boxes, or edit the numbers on the step), confirm the settings, then scan the non-contrast phase and answer the review question (does the range cover the whole liver?).
4. Bolus tracking: take the monitoring slice, then place the tracking region on the aorta. Tip: on the Images tab switch on "Show reference anatomy", then on the Contrast tab click the aorta marker on the tracking image; the region moves there. A region that is not on the aorta never triggers: monitoring ends at its time limit with an alert, and "Start scan manually" still works.
5. Arm the injector and press "Inject and arterial scan". The venous and delayed scans start by themselves at their set times. Then review the phases, send the images, and finish the aftercare steps. The Contrast tab shows injector pressure and the tracking curve; the Dose tab shows predicted and delivered dose; the Log tab lists events.

## What is real and what is assumed

Real: the CT volumes and organ labels from the dataset, the topogram geometry, the table and gantry geometry, the SOMATOM Force limits, and the protocol values taken from the cited OHSU protocol and the research notes (each with its source).

Assumed: every number that comes from neither a protocol file, the scanner file nor a research note is listed in the `assumptions` of that file and shows in the app with the tag "assumed". Patient height and weight are estimated from the CT (marked "estimated"). Step lists come from published material, not from watching a technologist; the design asks a CT technologist to check them. The contrast and dose models are simple and have not been validated.

## Add a patient

Five volunteers are built (`sub-000`, `sub-001`, `sub-002`, `sub-004`, `sub-005`). To build another from the dataset (read-only):

    PYTHONPATH=/mnt/CT_SCAN/work/python-libs:py /mnt/miniconda3/envs/ctm/bin/python tools/build_patient_pack.py --subject sub-003

It writes `data/patients/sub-003/`. Restart the server and the patient appears in the dropdown. Only `tools/build_patient_pack.py` needs `nibabel`.

## Run the tests

    cd py && /mnt/miniconda3/envs/ctm/bin/python -m pytest -q    # engine and server
    cd client && npm test                                         # client unit tests
    cd client && npm run build                                    # type check and build
    cd client && npm run e2e                                      # browser tests

The browser tests start their own server on port 8791 and drive Google Chrome (`/usr/bin/google-chrome`, headless, through Playwright; no browser download). They open the app with `?lowgfx`. One test performs the whole exam through the interface and writes screenshots to `client/e2e/screens/`; it takes about a minute.

## Known limits

- CT only. MRI is listed in the dropdown but disabled. The MRI data and design are in the research notes.
- One exam: multiphase liver. Other exams need protocol files in `data/protocols/`.
- The source scans were head first with the arms down, so slices show arms beside the body even though the simulated positioning puts them up.
- The 3D models are built in code. No downloaded models are installed; each download needs your approval (see the open items in the design).
- One simulated session per browser tab; sessions are not saved.
- Needs Node 20 (Vite 6, Vitest 4).
- Without a graphics card the 3D view is slow (see `?lowgfx` above).

## Where things are

- `data/protocols/ct/` protocol JSON; `data/scanners/` scanner JSON; `data/patients/` patient packs.
- `py/scansim/` the engine; `py/scansim_server/` the HTTP and WebSocket server; `py/tests/` their tests.
- `client/src/` the web client; `client/e2e/` the browser tests.
- `tools/build_patient_pack.py` builds patient packs.
- Research notes: `/mnt/CT_SCAN/docs/research/scan-room-sim/` (CT workflow, contrast, MRI workflow, MRI protocols, 3D models and prior art).
- Design: `/mnt/CT_SCAN/docs/superpowers/specs/2026-11-13-scan-room-simulator-design.md`.

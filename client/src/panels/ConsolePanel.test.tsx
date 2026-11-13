import { createEvent, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import type { Action, Snapshot } from '../api/types.gen'
import TopogramViewer from '../console/TopogramViewer'
import ContrastTab from '../console/ContrastTab'
import DoseTab, { DOSE_NOTE } from '../console/DoseTab'
import sampleJson from '../test/sampleSnapshot.json'
import { initialSessionState, useSession } from '../store/session'
import ConsolePanel from './ConsolePanel'

const sample = sampleJson as unknown as Snapshot
const sent: Action[] = []

function withTracking(state: string, extra: Partial<Snapshot['console']> = {}): Snapshot {
  const tracking = { ...sample.console.tracking!, state } as NonNullable<Snapshot['console']['tracking']>
  return { ...sample, console: { ...sample.console, tracking, ...extra } }
}

function load(snapshot: Snapshot): Snapshot {
  sent.length = 0
  useSession.setState({
    ...initialSessionState(),
    snapshot,
    send: vi.fn(async (a: Action) => {
      sent.push(a)
      return { ok: true, error: null }
    }),
  })
  return snapshot
}

beforeEach(() => load(sample))

describe('ContrastTab', () => {
  test('the manual start button appears only while monitoring', () => {
    const { unmount } = render(<ContrastTab snapshot={load(withTracking('monitoring'))} />)
    expect(screen.getByRole('button', { name: 'Start scan manually' })).toBeTruthy()
    unmount()
    render(<ContrastTab snapshot={load(withTracking('triggered'))} />)
    expect(screen.queryByRole('button', { name: 'Start scan manually' })).toBeNull()
  })

  test('the manual start button sends manual_start', () => {
    render(<ContrastTab snapshot={load(withTracking('manual'))} />)
    fireEvent.click(screen.getByRole('button', { name: 'Start scan manually' }))
    expect(sent).toEqual([{ type: 'manual_start' }])
  })

  test('the curve shows the trigger line at baseline plus threshold', () => {
    render(<ContrastTab snapshot={sample} />)
    expect(screen.getByText('Trigger 145 HU')).toBeTruthy()
    expect(screen.getByText(/182 \/ 325 psi/)).toBeTruthy()
  })

  test('the injector pressure and its limit are labelled assumed', () => {
    render(<ContrastTab snapshot={sample} />)
    const pressure = screen.getByText(/182 \/ 325 psi/)
    expect(within(pressure).getByText('assumed')).toBeTruthy()
  })

  test('reference points draw as labelled markers', () => {
    const snap = load(withTracking('monitoring', { reference_points: [{ name: 'aorta', label: 'Aorta', x_mm: -10, y_mm: 30 }] }))
    render(<ContrastTab snapshot={snap} />)
    expect(screen.getByText('Aorta')).toBeTruthy()
  })
})

describe('DoseTab', () => {
  test('the dose tab lists every series and the total', () => {
    render(<DoseTab snapshot={sample} />)
    const rows = within(screen.getByRole('table')).getAllByRole('row')
    expect(rows).toHaveLength(1 + 4)
    expect(screen.getByText(/Total DLP/).textContent).toContain('1021')
  })

  test('the total says it is an estimate and what it leaves out', () => {
    render(<DoseTab snapshot={sample} />)
    const note = screen.getByTestId('dose-note').textContent ?? ''
    expect(note).toBe(DOSE_NOTE)
    for (const words of ['model estimate', 'assumed', 'topograms', 'bolus-monitoring scans', 'stopped part-way adds the part']) {
      expect(note).toContain(words)
    }
    expect(within(screen.getByText(/Total DLP/).parentElement!).getByText('assumed')).toBeTruthy()
  })

  test('alerts are listed', () => {
    const snap = load({ ...sample, console: { ...sample.console, dose: { total_dlp_mgycm: 5, alerts: ['Dose above reference'] } } })
    render(<DoseTab snapshot={snap} />)
    expect(screen.getByText('Dose above reference')).toBeTruthy()
  })
})

describe('ConsolePanel', () => {
  test('has the five tabs and starts on Exam', () => {
    render(<ConsolePanel />)
    const names = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(names).toEqual(['Exam', 'Images', 'Contrast', 'Dose', 'Log'])
    expect(screen.getByText('CT Multiphase Liver')).toBeTruthy()
    expect(screen.getByText('Patient height')).toBeTruthy()
  })

  test('age and sex are marked assumed when the record lists them as not known', () => {
    const patient = { ...sample.patient, estimated_fields: ['age', 'sex', 'height_cm', 'weight_kg'] }
    load({ ...sample, patient })
    const { unmount } = render(<ConsolePanel />)
    expect(screen.getByText('58 y, M (assumed: the record is synthetic)')).toBeTruthy()
    expect(screen.getByText('172.0 cm (estimated)')).toBeTruthy()
    unmount()
    load({ ...sample, patient: { ...sample.patient, estimated_fields: [] } })
    render(<ConsolePanel />)
    expect(screen.getByText('58 y, M')).toBeTruthy()
  })

  test('the reference checkbox sends set_reference', async () => {
    render(<ConsolePanel />)
    fireEvent.click(screen.getByRole('tab', { name: 'Images' }))
    fireEvent.click(screen.getByLabelText('Show reference anatomy'))
    await waitFor(() => expect(sent).toEqual([{ type: 'set_reference', on: true }]))
  })

  test('the log lists newest first and marks voice lines', () => {
    load({
      ...sample,
      log: [
        { t_s: 5, kind: 'step', text: 'First thing' },
        { t_s: 65, kind: 'voice', text: 'Breathe in' },
        { t_s: 70, kind: 'alert', text: 'Pressure high' },
      ],
    })
    render(<ConsolePanel />)
    fireEvent.click(screen.getByRole('tab', { name: 'Log' }))
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items[0]).toContain('Pressure high')
    expect(items[2]).toContain('First thing')
    expect(screen.getByText('“Breathe in”').tagName).toBe('EM')
    expect(screen.getByText(/1:05/)).toBeTruthy()
  })

  test('the slice viewer says so for a series not yet acquired', () => {
    render(<ConsolePanel />)
    fireEvent.click(screen.getByRole('tab', { name: 'Images' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Arterial' }))
    expect(screen.getByText('Not acquired yet')).toBeTruthy()
  })

  test('a reconstruction that is not ready requests no image', () => {
    const series = sample.console.series!.map((x) =>
      x.id === 'noncontrast' ? { ...x, recons: x.recons.map((r) => ({ ...r, ready: false })) } : x,
    )
    load({ ...sample, console: { ...sample.console, series } })
    render(<ConsolePanel />)
    fireEvent.click(screen.getByRole('tab', { name: 'Images' }))
    expect(screen.getByText('Not acquired yet')).toBeTruthy()
    expect(screen.queryByAltText(/Non-contrast axial image/)).toBeNull()
  })

  test('the reconstruction selector stays when a not-ready plane is chosen', () => {
    const series = sample.console.series!.map((x) =>
      x.id === 'noncontrast'
        ? {
            ...x,
            recons: [
              ...x.recons,
              { plane: 'coronal' as const, thickness_mm: 5, increment_mm: 2.5, kernel: 'Br40', image_count: 100, ready: false },
            ],
          }
        : x,
    )
    load({ ...sample, console: { ...sample.console, series } })
    render(<ConsolePanel />)
    fireEvent.click(screen.getByRole('tab', { name: 'Images' }))
    fireEvent.change(screen.getByLabelText('Reconstruction'), { target: { value: 'coronal' } })
    expect(screen.getByText('Not acquired yet')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Reconstruction'), { target: { value: 'axial' } })
    expect(screen.getByAltText('Non-contrast axial image 1')).toBeTruthy()
  })

  test('the slice viewer fills the image url from the template', () => {
    render(<ConsolePanel />)
    fireEvent.click(screen.getByRole('tab', { name: 'Images' }))
    const img = screen.getByAltText('Non-contrast axial image 1') as HTMLImageElement
    expect(img.getAttribute('src')).toBe('/api/session/sample/series/noncontrast/axial/0.png')
  })

  test('shows a waiting note without a snapshot', () => {
    useSession.setState({ ...initialSessionState(), snapshot: null })
    render(<ConsolePanel />)
    expect(screen.getByText(/Start an exam/)).toBeTruthy()
  })
})

// jsdom has no PointerEvent, so the coordinates are set on the event by hand.
function pointer(kind: 'pointerMove' | 'pointerUp', el: Element, clientY: number) {
  const ev = createEvent[kind](el)
  Object.defineProperty(ev, 'clientY', { value: clientY })
  fireEvent(el, ev)
}

function editable(snapshot: Snapshot, edits: Record<string, string[]>): Snapshot {
  const mk = (key: string) => ({ key, label: key, type: 'number' as const, value: 0, default: 0, source: 'protocol' as const, editable: true })
  return {
    ...snapshot,
    stages: snapshot.stages.map((st) => ({
      ...st,
      steps: st.steps.map((step) => {
        const idle = step.status === 'running' ? { ...step, status: 'done' as const } : step
        return edits[step.id] ? { ...idle, fields: edits[step.id].map(mk) } : idle
      }),
    })),
  }
}

/** The sample with nothing running, so that its fields can be edited (as when the exam is between steps). */
function idle(snapshot: Snapshot = sample): Snapshot {
  return {
    ...snapshot,
    stages: snapshot.stages.map((st) => ({
      ...st,
      steps: st.steps.map((step) => (step.status === 'running' ? { ...step, status: 'done' as const } : step)),
    })),
  }
}

function withField(snapshot: Snapshot, stepId: string, key: string, change: Record<string, unknown>): Snapshot {
  return {
    ...snapshot,
    stages: snapshot.stages.map((st) => ({
      ...st,
      steps: st.steps.map((step) =>
        step.id === stepId ? { ...step, fields: step.fields?.map((f) => (f.key === key ? { ...f, ...change } : f)) } : step,
      ),
    })),
  }
}

const ALL = 'noncontrast+arterial+venous+delayed'
const IDS = ALL.split('+')
const BOX = { top: 0, height: 512, left: 0, width: 256, bottom: 512, right: 256, x: 0, y: 0, toJSON() {} }

function renderTopogram(snap: Snapshot): SVGSVGElement {
  const { container } = render(<TopogramViewer topogram={snap.console.topograms![0]} snapshot={snap} interactive />)
  const svg = container.querySelector('svg')!
  svg.getBoundingClientRect = () => BOX
  return svg
}

const geometry = (el: Element) => [Number(el.getAttribute('y')), Number(el.getAttribute('height'))]

describe('editing from the images', () => {
  test('a drag shows a dashed pending box and, on release, sets the edge of every series to whole millimetres', async () => {
    const svg = renderTopogram(load(idle()))
    expect(screen.queryByTestId(`pending-${ALL}`)).toBeNull()   // the fields equal the plan: nothing is pending
    fireEvent.pointerDown(screen.getByTestId(`handle-${ALL}-end_mm`))
    pointer('pointerMove', svg, 300.4)
    expect(sent).toEqual([])
    // start -80 mm is row 40; the dragged end 180 mm is row 300. The accepted box stays where the plan is.
    expect(geometry(screen.getByTestId(`pending-${ALL}`))).toEqual([40, 260])
    expect(screen.getByTestId(`pending-${ALL}`).getAttribute('stroke-dasharray')).toBeTruthy()
    expect(geometry(screen.getByTestId(`box-${ALL}`))).toEqual([40, 400])
    pointer('pointerUp', svg, 300.4)
    await waitFor(() => expect(sent).toHaveLength(4))
    expect(sent).toEqual(IDS.map((id) => ({ type: 'set_field', step_id: 'plan_ranges', key: `${id}.end_mm`, value: 180 })))
  })

  test('field values that differ from the plan stay drawn as a dashed box until the step accepts them', () => {
    let snap = idle()
    for (const id of IDS) snap = withField(snap, 'plan_ranges', `${id}.end_mm`, { value: 250 })
    renderTopogram(load(snap))
    expect(geometry(screen.getByTestId(`pending-${ALL}`))).toEqual([40, 330])    // -80 to 250 mm
    expect(geometry(screen.getByTestId(`box-${ALL}`))).toEqual([40, 400])        // the plan: -80 to 320 mm
    expect(screen.getByText(/not accepted yet/)).toBeTruthy()
  })

  test('before the first plan the pre-filled ranges are drawn dashed and can be dragged', () => {
    const snap = idle()
    renderTopogram(load({ ...snap, console: { ...snap.console, series: [] } }))
    expect(screen.queryByTestId(`box-${ALL}`)).toBeNull()
    expect(geometry(screen.getByTestId(`pending-${ALL}`))).toEqual([40, 400])
    expect(screen.getByTestId(`handle-${ALL}-start_mm`)).toBeTruthy()
  })

  test('a group drag stops at the first rejected series edit and shows why', async () => {
    const snap = load(idle())
    let calls = 0
    useSession.setState({
      send: vi.fn(async (a: Action) => {
        sent.push(a)
        calls += 1
        return calls === 2 ? { ok: false, error: 'arterial.end_mm is past table travel' } : { ok: true, error: null }
      }),
    })
    const svg = renderTopogram(snap)
    fireEvent.pointerDown(screen.getByTestId(`handle-${ALL}-end_mm`))
    pointer('pointerUp', svg, 300)
    expect((await screen.findByRole('alert')).textContent).toContain('past table travel')
    expect(sent.map((a) => (a as { key: string }).key)).toEqual(['noncontrast.end_mm', 'arterial.end_mm'])
    fireEvent.pointerDown(screen.getByTestId(`handle-${ALL}-end_mm`))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  test('no handles and no pending box while a step is running, even on editable fields', () => {
    renderTopogram(load(sample))                                  // the sample has a running step
    expect(screen.queryByTestId(`handle-${ALL}-end_mm`)).toBeNull()
    expect(screen.queryByTestId(`pending-${ALL}`)).toBeNull()
    expect(screen.getByTestId(`box-${ALL}`)).toBeTruthy()         // the accepted plan is still shown
  })

  test('a range whose fields are not editable has no drag handles', () => {
    let snap = idle()
    for (const id of IDS) snap = withField(snap, 'plan_ranges', `${id}.end_mm`, { editable: false })
    renderTopogram(load(snap))
    expect(screen.queryByTestId(`handle-${ALL}-end_mm`)).toBeNull()
  })

  test('the monitoring level can be dragged before the slice is taken and is drawn dashed until then', async () => {
    const level = { key: 'slice_mm', label: 'Monitoring level', type: 'number' as const, value: 120, default: 120, source: 'assumption' as const, editable: true }
    let snap = editable(sample, { monitoring_slice: [] })
    snap = { ...snap, stages: snap.stages.map((st) => ({ ...st, steps: st.steps.map((x) => (x.id === 'monitoring_slice' ? { ...x, fields: [level] } : x)) })) }
    const svg = renderTopogram(load({ ...snap, console: { ...snap.console, tracking: null } }))
    expect(screen.queryByTestId('level')).toBeNull()
    expect(screen.getByTestId('pending-level').textContent).toContain('Level 120 mm, not taken yet')
    fireEvent.pointerDown(screen.getByTestId('handle-level'))
    pointer('pointerUp', svg, 180.2)
    await waitFor(() => expect(sent).toEqual([{ type: 'set_field', step_id: 'monitoring_slice', key: 'slice_mm', value: 60 }]))
  })

  test('a taken monitoring level is solid, and a different field value is drawn dashed beside it', () => {
    const level = { key: 'slice_mm', label: 'Monitoring level', type: 'number' as const, value: 100, default: 120, source: 'assumption' as const, editable: true }
    let snap = idle()
    snap = { ...snap, stages: snap.stages.map((st) => ({ ...st, steps: st.steps.map((x) => (x.id === 'monitoring_slice' ? { ...x, fields: [level] } : x)) })) }
    renderTopogram(load(snap))
    expect(screen.getByTestId('level').textContent).toContain('Tracking 140 mm')
    expect(screen.getByTestId('pending-level').textContent).toContain('Level 100 mm')
  })

  test('the level cannot be dragged once its field is locked', () => {
    renderTopogram(load(idle()))                                  // the sample's monitoring step has no editable field
    expect(screen.getByTestId('level')).toBeTruthy()
    expect(screen.queryByTestId('handle-level')).toBeNull()
    expect(screen.queryByTestId('pending-level')).toBeNull()
  })

  test('a rejected x leaves y unsent and shows the message', async () => {
    const snap = load(editable(sample, { place_roi: ['roi_x_mm', 'roi_y_mm'] }))
    useSession.setState({
      send: vi.fn(async (a: Action) => {
        sent.push(a)
        return { ok: false, error: 'roi_x_mm must be within -200 and 200' }
      }),
    })
    render(<ContrastTab snapshot={snap} />)
    const box = screen.getByAltText('Tracking image').parentElement!
    box.getBoundingClientRect = () => ({ top: 0, height: 200, left: 0, width: 200, bottom: 200, right: 200, x: 0, y: 0, toJSON() {} })
    fireEvent.click(box, { clientX: 100, clientY: 150 })
    expect((await screen.findByRole('alert')).textContent).toContain('roi_x_mm must be within')
    expect(sent.map((a) => (a as { key: string }).key)).toEqual(['roi_x_mm'])
  })

  test('clicking the tracking image places the region around the image centre', async () => {
    const snap = load(editable(sample, { place_roi: ['roi_x_mm', 'roi_y_mm'] }))
    render(<ContrastTab snapshot={snap} />)
    const box = screen.getByAltText('Tracking image').parentElement!
    box.getBoundingClientRect = () => ({ top: 0, height: 200, left: 0, width: 200, bottom: 200, right: 200, x: 0, y: 0, toJSON() {} })
    fireEvent.click(box, { clientX: 100, clientY: 150 })
    await waitFor(() => expect(sent).toHaveLength(2))
    expect(sent).toEqual([
      { type: 'set_field', step_id: 'place_roi', key: 'roi_x_mm', value: 0 },
      { type: 'set_field', step_id: 'place_roi', key: 'roi_y_mm', value: 100 },
    ])
  })

  test('a clicked region is drawn dashed beside the accepted one until the step is performed', () => {
    const roi = (x: number) => {
      const mk = (key: string, value: number) => ({ key, label: key, type: 'number' as const, value, default: value, source: 'assumption' as const, editable: true })
      const snap = editable(sample, { place_roi: [] })
      const fields = [mk('roi_x_mm', x), mk('roi_y_mm', 38), mk('roi_r_mm', 8)]
      return { ...snap, stages: snap.stages.map((st) => ({ ...st, steps: st.steps.map((s) => (s.id === 'place_roi' ? { ...s, fields } : s)) })) }
    }
    const { unmount } = render(<ContrastTab snapshot={load(roi(-12))} />)       // the fields equal the accepted region
    expect(screen.getByTestId('roi').getAttribute('cx')).toBe('-12')
    expect(screen.queryByTestId('pending-roi')).toBeNull()
    unmount()
    render(<ContrastTab snapshot={load(roi(30))} />)
    expect(screen.getByTestId('roi').getAttribute('cx')).toBe('-12')
    const pending = screen.getByTestId('pending-roi')
    expect(pending.getAttribute('cx')).toBe('30')
    expect(pending.getAttribute('stroke-dasharray')).toBeTruthy()
    expect(screen.getByText(/not accepted yet/)).toBeTruthy()
  })

  test('before a region is accepted only the dashed one is drawn; while a step runs only the accepted one', () => {
    const mk = (key: string, value: number) => ({ key, label: key, type: 'number' as const, value, default: value, source: 'assumption' as const, editable: true })
    const base = editable(sample, { place_roi: [] })
    const fields = [mk('roi_x_mm', 10), mk('roi_y_mm', 45), mk('roi_r_mm', 8)]
    const snap = { ...base, stages: base.stages.map((st) => ({ ...st, steps: st.steps.map((s) => (s.id === 'place_roi' ? { ...s, fields } : s)) })) }
    const tracking = { ...sample.console.tracking!, state: 'slice_acquired' as const, baseline_hu: null, samples: [] }
    const { unmount } = render(<ContrastTab snapshot={load({ ...snap, console: { ...snap.console, tracking } })} />)
    expect(screen.queryByTestId('roi')).toBeNull()
    expect(screen.getByTestId('pending-roi').getAttribute('cx')).toBe('10')
    unmount()
    render(<ContrastTab snapshot={load(sample)} />)
    expect(screen.getByTestId('roi')).toBeTruthy()
    expect(screen.queryByTestId('pending-roi')).toBeNull()
  })
})

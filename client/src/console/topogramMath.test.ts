import { describe, expect, test } from 'vitest'
import type { Snapshot, TopogramView } from '../api/types.gen'
import sampleJson from '../test/sampleSnapshot.json'
import { displayRange, editableNumber, isAccepted, pendingRanges, plannedTopogramEndMm, rangeFieldKeys, rowAtFraction, rowWindow, stretchGrey, clampToRevealed, cropColumns, findStepField, formatClock, groupRanges, mmForRow, rowForMm } from './topogramMath'

const t = { row_mm: 3, row0_from_landmark_mm: -300, revealed_from_row: 80, revealed_to_row: 250 } as TopogramView
const sample = sampleJson as unknown as Snapshot

describe('topogram geometry', () => {
  test('rows and millimetres convert both ways', () => {
    expect(rowForMm(t, 0)).toBe(100)
    expect(mmForRow(t, 100)).toBe(0)
    expect(mmForRow(t, rowForMm(t, 137))).toBeCloseTo(137)
  })

  test('a dragged edge cannot leave the acquired rows', () => {
    expect(clampToRevealed(t, -900)).toBe(mmForRow(t, 80))
    expect(clampToRevealed(t, 900)).toBe(mmForRow(t, 250))
    expect(clampToRevealed(t, 0)).toBe(0)
  })

  test('only the central 256 columns are shown, fewer when the image is narrower', () => {
    expect(cropColumns(512)).toEqual({ x0: 128, width: 256 })
    expect(cropColumns(200)).toEqual({ x0: 0, width: 200 })
  })
})

describe('helpers', () => {
  test('clock times read as m:ss', () => {
    expect(formatClock(0)).toBe('0:00')
    expect(formatClock(125.4)).toBe('2:05')
  })

  test('series that share a range collapse into one box', () => {
    const groups = groupRanges(sample.console.series ?? [])
    expect(groups).toHaveLength(1)
    expect(groups[0].label).toBe('All phases')
    expect(groups[0].ids).toHaveLength(4)
  })

  test('step fields are found by step and key', () => {
    expect(findStepField(sample, 'plan_ranges', 'noncontrast.start_mm')?.editable).toBe(true)
    expect(findStepField(sample, 'plan_ranges', 'start_mm')).toBeUndefined()
    expect(findStepField(sample, 'plan_ranges', 'nope')).toBeUndefined()
  })
})

describe('rangeFieldKeys', () => {
  const withFields = (keys: string[]): Snapshot => ({
    ...sample,
    stages: sample.stages.map((st) => ({
      ...st,
      steps: st.steps.map((step) => {
        const idle = step.status === 'running' ? { ...step, status: 'done' as const } : step
        const fields = keys.map((key) => ({ key, label: key, type: 'number' as const, value: 0, default: 0, source: 'protocol' as const, editable: true }))
        return step.id === 'plan_ranges' ? { ...idle, fields } : idle
      }),
    })),
  })

  test('each series has its own key, as the engine names them', () => {
    const snap = withFields(['a.end_mm', 'b.end_mm'])
    expect(rangeFieldKeys(snap, ['a', 'b'], 'end_mm')).toEqual(['a.end_mm', 'b.end_mm'])
  })

  test('a bare key is not a range field: there is no fallback', () => {
    expect(rangeFieldKeys(withFields(['end_mm']), ['a', 'b'], 'end_mm')).toEqual([])
    expect(rangeFieldKeys(withFields(['end_mm']), ['a'], 'end_mm')).toEqual([])
  })

  test('one missing series key leaves the whole group without keys', () => {
    expect(rangeFieldKeys(withFields(['a.end_mm']), ['a', 'b'], 'end_mm')).toEqual([])
  })

  test('nothing can be edited while a step is running', () => {
    expect(rangeFieldKeys(sample, ['noncontrast'], 'end_mm')).toEqual([])
  })
})

/** The sample with no step running, so its fields can be edited; `values` replaces field values of plan_ranges. */
function idle(values: Record<string, number> = {}, base: Snapshot = sample): Snapshot {
  return {
    ...base,
    stages: base.stages.map((st) => ({
      ...st,
      steps: st.steps.map((step) => ({
        ...step,
        status: step.status === 'running' ? ('done' as const) : step.status,
        fields: step.id === 'plan_ranges' ? step.fields?.map((f) => (f.key in values ? { ...f, value: values[f.key] } : f)) : step.fields,
      })),
    })),
  }
}

describe('pending ranges', () => {
  const series = sample.console.series ?? []

  test('the fields of the plan step give one shared pending box, equal to the accepted plan', () => {
    const pending = pendingRanges(idle())
    expect(pending).toHaveLength(1)
    expect(pending[0]).toMatchObject({ label: 'All phases', start_mm: -80, end_mm: 320, fov_mm: 400, fov_center_x_mm: 0 })
    expect(pending[0].ids).toEqual(['noncontrast', 'arterial', 'venous', 'delayed'])
    expect(isAccepted(pending[0], series)).toBe(true)
  })

  test('a changed field makes its range pending, and unlinked ranges split into one box per series', () => {
    const all = pendingRanges(idle({ 'noncontrast.end_mm': 250, 'arterial.end_mm': 250, 'venous.end_mm': 250, 'delayed.end_mm': 250 }))
    expect(all).toHaveLength(1)
    expect(isAccepted(all[0], series)).toBe(false)
    const split = pendingRanges(idle({ 'arterial.end_mm': 250 }))
    expect(split.map((g) => g.label)).toEqual(['Non-contrast', 'Arterial', 'Venous', '4 minute delay'])
    expect(split.map((g) => isAccepted(g, series))).toEqual([true, false, true, true])
  })

  test('before the first plan there is no plan to match, so the pending box is not accepted', () => {
    expect(isAccepted(pendingRanges(idle())[0], [])).toBe(false)
  })

  test('there are no pending ranges while a step is running or the fields are locked', () => {
    expect(pendingRanges(sample)).toEqual([])
    const locked = idle()
    const step = locked.stages.flatMap((st) => st.steps).find((x) => x.id === 'plan_ranges')!
    step.fields = step.fields?.map((f) => ({ ...f, editable: false }))
    expect(pendingRanges(locked)).toEqual([])
  })

  test('a number is read from a field only while it can be edited', () => {
    expect(editableNumber(idle(), 'plan_ranges', 'fov_mm')).toBe(400)
    expect(editableNumber(sample, 'plan_ranges', 'fov_mm')).toBeNull()
    expect(editableNumber(idle(), 'plan_ranges', 'link_ranges')).toBeNull()
    expect(editableNumber(idle(), 'plan_ranges', 'nope')).toBeNull()
  })
})

describe('row window', () => {
  const full = { rows: 512, revealed_from_row: 205, revealed_to_row: 376, row_mm: 1, row0_from_landmark_mm: -200 } as TopogramView

  test('shows the acquired rows plus a margin', () => {
    expect(rowWindow(full)).toEqual({ top: 193, rows: 195 })
  })

  test('is null before anything is acquired', () => {
    expect(rowWindow({ ...full, revealed_from_row: 205, revealed_to_row: 205 })).toBeNull()
  })

  test('never zooms in closer than the minimum and stays inside the image', () => {
    const early = rowWindow({ ...full, revealed_to_row: 210 })!
    expect(early.rows).toBeGreaterThanOrEqual(96)
    const edge = rowWindow({ ...full, revealed_from_row: 500, revealed_to_row: 512 })!
    expect(edge.top + edge.rows).toBeLessThanOrEqual(512)
    expect(edge.rows).toBeGreaterThanOrEqual(96)
  })

  test('a position in the window maps back to the right row and millimetre', () => {
    const w = rowWindow(full)!
    expect(rowAtFraction(w, 0)).toBe(193)
    expect(rowAtFraction(w, 1)).toBe(388)
    expect(rowAtFraction(w, 2)).toBe(388)
    expect(mmForRow(full, rowAtFraction(w, 0.5))).toBe(-200 + 193 + 97.5)
  })
})

describe('display range', () => {
  const grey = (values: number[]) => Uint8ClampedArray.from(values.flatMap((v) => [v, v, v, 255]))

  test('ignores zero pixels and finds the 1st to 99th percentile', () => {
    const values = [0, 0, 0, ...Array.from({ length: 100 }, (_, i) => i + 100)]
    expect(displayRange(grey(values))).toEqual({ lo: 100, hi: 198 })
  })

  test('an empty image has no range', () => {
    expect(displayRange(grey([0, 0]))).toBeNull()
  })

  test('stretching sends lo to black and hi to white and keeps zero', () => {
    const px = grey([0, 100, 150, 200])
    stretchGrey(px, 100, 200)
    expect([px[0], px[4], px[8], px[12]]).toEqual([0, 0, 128, 255])
  })
})

describe('row window while the scan runs', () => {
  const running = { rows: 512, revealed_from_row: 205, revealed_to_row: 250, row_mm: 1, row0_from_landmark_mm: -200, complete: false } as TopogramView

  test('spans the planned run so the frame does not move', () => {
    expect(rowWindow(running, 312)).toEqual({ top: 193, rows: 319 })
    expect(rowWindow(running, 312)).toEqual(rowWindow({ ...running, revealed_to_row: 300 }, 312))
  })

  test('shrinks to the acquired rows once the scan is complete', () => {
    expect(rowWindow({ ...running, complete: true, revealed_to_row: 376 }, 312)).toEqual({ top: 193, rows: 195 })
  })

  test('reads the planned end from the step fields', () => {
    const snap = JSON.parse(JSON.stringify(sample)) as Snapshot
    const step = snap.stages.flatMap((s) => s.steps).find((s) => s.id === 'topogram_ap')!
    step.fields = [
      { ...(sample.stages[0].steps[0].fields?.[0] ?? ({} as never)), key: 'start_mm', value: -120 },
      { ...(sample.stages[0].steps[0].fields?.[0] ?? ({} as never)), key: 'length_mm', value: '512' },
    ] as never
    expect(plannedTopogramEndMm(snap, 'AP')).toBe(392)
    expect(plannedTopogramEndMm(snap, 'LAT')).toBeNull()
  })
})

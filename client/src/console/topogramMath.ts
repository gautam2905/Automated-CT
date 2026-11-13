import type { FieldView, SeriesView, Snapshot, TopogramView } from '../api/types.gen'

export const MAX_SHOWN_COLUMNS = 256

export function rowForMm(t: TopogramView, mm: number): number {
  return (mm - t.row0_from_landmark_mm) / t.row_mm
}

export function mmForRow(t: TopogramView, row: number): number {
  return t.row0_from_landmark_mm + row * t.row_mm
}

/** Keeps a position inside the rows the scanner has acquired so far. */
export function clampToRevealed(t: TopogramView, mm: number): number {
  const lo = mmForRow(t, t.revealed_from_row)
  const hi = mmForRow(t, t.revealed_to_row)
  return Math.min(hi, Math.max(lo, mm))
}

export const WINDOW_MARGIN_ROWS = 12
export const MIN_WINDOW_ROWS = 96

export interface RowWindow {
  top: number
  rows: number
}

/**
 * The rows worth showing: those acquired so far plus a margin, or null before anything is acquired.
 * While the scan is still running, the window already spans the whole planned run (`plannedEndMm`), so the
 * frame stays put and the image visibly grows into it.
 */
export function rowWindow(t: TopogramView, plannedEndMm?: number | null): RowWindow | null {
  if (t.revealed_to_row <= t.revealed_from_row) return null
  const minRows = Math.min(MIN_WINDOW_ROWS, t.rows)
  const plannedRow = !t.complete && plannedEndMm != null ? Math.ceil(rowForMm(t, plannedEndMm)) : 0
  let top = Math.max(0, t.revealed_from_row - WINDOW_MARGIN_ROWS)
  let bottom = Math.min(t.rows, Math.max(t.revealed_to_row, plannedRow) + WINDOW_MARGIN_ROWS)
  if (bottom - top < minRows) bottom = Math.min(t.rows, top + minRows)
  if (bottom - top < minRows) top = Math.max(0, bottom - minRows)
  return { top, rows: bottom - top }
}

/** A position inside the window (0 = its top edge, 1 = its bottom edge) as a row of the full image. */
export function rowAtFraction(w: RowWindow, fraction: number): number {
  return w.top + Math.min(1, Math.max(0, fraction)) * w.rows
}

const LOW_PERCENTILE = 0.01
const HIGH_PERCENTILE = 0.99

/** The 1st and 99th percentile of the non-zero grey values (red channel of RGBA data), or null if there are none. */
export function displayRange(rgba: ArrayLike<number>): { lo: number; hi: number } | null {
  const counts = new Array<number>(256).fill(0)
  let total = 0
  for (let i = 0; i < rgba.length; i += 4) {
    if (rgba[i] > 0) {
      counts[rgba[i]] += 1
      total += 1
    }
  }
  if (total === 0) return null
  const at = (fraction: number): number => {
    let seen = 0
    for (let v = 1; v < 256; v += 1) {
      seen += counts[v]
      if (seen >= fraction * total) return v
    }
    return 255
  }
  return { lo: at(LOW_PERCENTILE), hi: at(HIGH_PERCENTILE) }
}

/** Stretches grey values so `lo` shows black and `hi` white, in place; zero stays zero. */
export function stretchGrey(rgba: Uint8ClampedArray, lo: number, hi: number): void {
  const span = Math.max(1, hi - lo)
  for (let i = 0; i < rgba.length; i += 4) {
    if (rgba[i] === 0) continue
    const v = Math.round(((rgba[i] - lo) / span) * 255)
    rgba[i] = rgba[i + 1] = rgba[i + 2] = v
  }
}

/** The stored topogram is far wider than a body; only its central columns are shown. */
export function cropColumns(cols: number): { x0: number; width: number } {
  const width = Math.min(cols, MAX_SHOWN_COLUMNS)
  return { x0: Math.floor((cols - width) / 2), width }
}

export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  const s = whole % 60
  return `${Math.floor(whole / 60)}:${s < 10 ? '0' : ''}${s}`
}

export function findStepField(snapshot: Snapshot, stepId: string, key: string): FieldView | undefined {
  for (const stage of snapshot.stages) {
    const step = stage.steps.find((s) => s.id === stepId)
    if (step) return step.fields?.find((f) => f.key === key)
  }
  return undefined
}

/** Where the planned topogram run of a view ends (start plus length), from its step's fields. */
export function plannedTopogramEndMm(snapshot: Snapshot, view: TopogramView['view']): number | null {
  const step = view === 'AP' ? 'topogram_ap' : 'topogram_lat'
  const start = findStepField(snapshot, step, 'start_mm')?.value
  const length = findStepField(snapshot, step, 'length_mm')?.value
  const num = (v: unknown): number | null => (typeof v === 'number' ? v : typeof v === 'string' && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null)
  const s = num(start)
  const l = num(length)
  return s == null || l == null ? null : s + l
}

export function isAnyStepRunning(snapshot: Snapshot): boolean {
  return snapshot.stages.some((stage) => stage.steps.some((s) => s.status === 'running'))
}

/** An edit by drag or click is allowed only when the field is editable and nothing is running. */
export function canEditField(snapshot: Snapshot, stepId: string, key: string): boolean {
  return findStepField(snapshot, stepId, key)?.editable === true && !isAnyStepRunning(snapshot)
}

/** The number a step field holds now, or null when the field is missing, locked or not a number. */
export function editableNumber(snapshot: Snapshot, stepId: string, key: string): number | null {
  const value = findStepField(snapshot, stepId, key)?.value
  return canEditField(snapshot, stepId, key) && typeof value === 'number' ? value : null
}

export interface RangeGroup {
  ids: string[]
  label: string
  start_mm: number
  end_mm: number
  fov_mm: number
  fov_center_x_mm: number
}

/** One box per series, or a single "All phases" box when every series shares one range. */
function mergeShared(singles: RangeGroup[]): RangeGroup[] {
  const first = singles[0]
  const shared = singles.length > 1 && singles.every((g) => g.start_mm === first.start_mm && g.end_mm === first.end_mm)
  return shared ? [{ ...first, ids: singles.flatMap((g) => g.ids), label: 'All phases' }] : singles
}

/** The accepted ranges: what the series plans hold. */
export function groupRanges(series: SeriesView[]): RangeGroup[] {
  return mergeShared(
    series.map((s) => {
      const p = s.plan
      return { ids: [s.id], label: s.label, start_mm: p.start_mm, end_mm: p.end_mm, fov_mm: p.fov_mm, fov_center_x_mm: p.fov_center_x_mm }
    }),
  )
}

const START_SUFFIX = '.start_mm'

/**
 * The pending ranges: what the fields of step `plan_ranges` hold now, which performing that step would accept.
 * Empty unless every range field can be edited, so there is nothing to drag while the step is locked or running.
 */
export function pendingRanges(snapshot: Snapshot): RangeGroup[] {
  const fields = snapshot.stages.flatMap((st) => st.steps).find((s) => s.id === 'plan_ranges')?.fields ?? []
  const fov = editableNumber(snapshot, 'plan_ranges', 'fov_mm')
  const centre = editableNumber(snapshot, 'plan_ranges', 'fov_center_x_mm')
  const singles: RangeGroup[] = []
  for (const field of fields.filter((f) => f.key.endsWith(START_SUFFIX))) {
    const id = field.key.slice(0, -START_SUFFIX.length)
    const start = editableNumber(snapshot, 'plan_ranges', field.key)
    const end = editableNumber(snapshot, 'plan_ranges', `${id}.end_mm`)
    if (start == null || end == null || fov == null || centre == null) return []
    singles.push({ ids: [id], label: field.label.replace(/ start$/, ''), start_mm: start, end_mm: end, fov_mm: fov, fov_center_x_mm: centre })
  }
  return mergeShared(singles)
}

/** True when every series of the group is already planned with exactly this range and field of view. */
export function isAccepted(group: RangeGroup, series: SeriesView[]): boolean {
  return group.ids.every((id) => {
    const p = series.find((s) => s.id === id)?.plan
    return p != null && p.start_mm === group.start_mm && p.end_mm === group.end_mm && p.fov_mm === group.fov_mm && p.fov_center_x_mm === group.fov_center_x_mm
  })
}

export type RangeEdge = 'start_mm' | 'end_mm'

/** Field keys on step `plan_ranges` that set one edge for the series `ids`, or none if any is missing or locked. */
export function rangeFieldKeys(snapshot: Snapshot, ids: string[], edge: RangeEdge): string[] {
  const keys = ids.map((id) => `${id}.${edge}`)
  return keys.every((key) => canEditField(snapshot, 'plan_ranges', key)) ? keys : []
}

export function trackingFov(series: SeriesView[]): number {
  const s = series.find((x) => x.id === 'arterial') ?? series[0]
  return s?.plan.fov_mm ?? 0
}

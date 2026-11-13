import { useEffect, useRef, useState, type RefObject } from 'react'
import type { Snapshot, TopogramView } from '../api/types.gen'
import { useSession } from '../store/session'
import {
  canEditField,
  clampToRevealed,
  cropColumns,
  displayRange,
  editableNumber,
  groupRanges,
  isAccepted,
  mmForRow,
  pendingRanges,
  plannedTopogramEndMm,
  rangeFieldKeys,
  rowAtFraction,
  rowForMm,
  rowWindow,
  type RangeEdge,
  type RangeGroup,
  stretchGrey,
} from './topogramMath'

const AMBER = '#e0a020'
const REF_STROKE = '#8fa8b5'
const BOX_STROKE = '#4fc3d4'
const FONT = 9
const HANDLE = 10
const DASH = '6 4'

type Drag = { kind: 'edge'; group: RangeGroup; edge: RangeEdge; mm: number } | { kind: 'level'; mm: number }
type Begin = (d: Drag) => (e: React.PointerEvent) => void
type Edit = { step_id: string; key: string }

/**
 * Draws the topogram image into a canvas of the full image size, stretched to its own grey range.
 * A load that finishes after a newer one has already drawn is skipped; an older load is never cancelled,
 * so on a slow page the last loaded image stays on screen until a newer one arrives.
 */
function useTopogramImage(url: string, x0: number, width: number, height: number) {
  const ref = useRef<HTMLCanvasElement>(null)
  const issued = useRef(0)
  const drawn = useRef(0)
  useEffect(() => {
    issued.current += 1
    const mine = issued.current
    const img = new Image()
    img.onload = () => {
      const ctx = ref.current?.getContext('2d', { willReadFrequently: true })
      if (!ctx || mine < drawn.current) return
      drawn.current = mine
      ctx.drawImage(img, x0, 0, width, height, 0, 0, width, height)
      const pixels = ctx.getImageData(0, 0, width, height)
      const range = displayRange(pixels.data)
      if (!range) return
      stretchGrey(pixels.data, range.lo, range.hi)
      ctx.putImageData(pixels, 0, 0)
    }
    img.src = url
  }, [url, x0, width, height])
  return ref
}

/**
 * Dragging on the overlay. While the pointer is down the dragged line follows it; on release the new value
 * is sent to the step's fields, one edit after another. The first rejection stops the rest and is kept to show.
 * A drag only changes the fields: the dashed drawing stays until the step is performed and accepts them.
 */
function useDrag(snapshot: Snapshot, svgRef: RefObject<SVGSVGElement | null>, mmAt: (clientY: number) => number) {
  const send = useSession((s) => s.send)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [rejection, setRejection] = useState<string | null>(null)
  const sendInOrder = async (edits: Edit[], value: number) => {
    for (const edit of edits) {
      const result = await send({ type: 'set_field', ...edit, value })
      if (!result.ok) return setRejection(result.error ?? `${edit.key} was not changed`)
    }
  }
  const begin: Begin = (d) => (e) => {
    setRejection(null)
    svgRef.current?.setPointerCapture?.(e.pointerId)
    setDrag(d)
  }
  const move = (e: React.PointerEvent) => {
    if (drag) setDrag({ ...drag, mm: mmAt(e.clientY) })
  }
  const release = (e: React.PointerEvent) => {
    if (!drag) return
    setDrag(null)
    const edits: Edit[] =
      drag.kind === 'level'
        ? [{ step_id: 'monitoring_slice', key: 'slice_mm' }]
        : rangeFieldKeys(snapshot, drag.group.ids, drag.edge).map((key) => ({ step_id: 'plan_ranges', key }))
    sendInOrder(edits, mmAt(e.clientY)).catch((err: unknown) =>
      setRejection(err instanceof Error ? err.message : 'The change could not be sent'),
    )
  }
  return { drag, rejection, begin, move, release, cancel: () => setDrag(null) }
}

interface OverlayProps {
  topogram: TopogramView
  width: number
  snapshot: Snapshot
  drag: Drag | null
  begin: Begin
}

interface BoxProps {
  group: RangeGroup
  topogram: TopogramView
  width: number
  startMm: number
  endMm: number
  pending?: boolean
}

function boxX(g: RangeGroup, t: TopogramView, width: number): [number, number] {
  const mid = width / 2 + g.fov_center_x_mm / t.col_mm
  const half = g.fov_mm / 2 / t.col_mm
  return [Math.max(0, mid - half), Math.min(width, mid + half)]
}

/** A range box: solid for a range the plan holds, dashed for one that waits to be accepted. */
function RangeBox({ group, topogram: t, width, startMm, endMm, pending = false }: BoxProps) {
  const [x1, x2] = boxX(group, t, width)
  const top = Math.min(rowForMm(t, startMm), rowForMm(t, endMm))
  const height = Math.abs(rowForMm(t, endMm) - rowForMm(t, startMm))
  const length = `${group.label}, ${Math.round(Math.abs(endMm - startMm))} mm`
  return (
    <g>
      <rect
        data-testid={`${pending ? 'pending' : 'box'}-${group.ids.join('+')}`}
        x={x1}
        y={top}
        width={x2 - x1}
        height={height}
        fill="var(--accent, #166b78)"
        fillOpacity={pending ? 0.05 : 0.12}
        stroke={pending ? AMBER : BOX_STROKE}
        strokeDasharray={pending ? DASH : undefined}
        strokeWidth={1.2}
      />
      <text x={x1 + 3} y={pending ? top + height - 3 : top + FONT + 2} fontSize={FONT} fill={pending ? AMBER : '#8fe0ee'}>
        {pending ? `${length}, not accepted yet` : length}
      </text>
    </g>
  )
}

/** The two grab strips of a pending range, one on each edge. */
function EdgeHandles({ group, topogram: t, width, startMm, endMm, begin }: BoxProps & { begin: Begin }) {
  const [x1, x2] = boxX(group, t, width)
  const strip = (edge: RangeEdge, mm: number) => (
    <rect
      data-testid={`handle-${group.ids.join('+')}-${edge}`}
      className="topogram__handle"
      x={x1}
      width={x2 - x1}
      y={rowForMm(t, mm) - HANDLE}
      height={HANDLE * 2}
      onPointerDown={begin({ kind: 'edge', group, edge, mm })}
    />
  )
  return (
    <>
      {strip('start_mm', startMm)}
      {strip('end_mm', endMm)}
    </>
  )
}

/**
 * Accepted ranges as solid boxes and, while "Plan ranges" can be edited, the ranges its fields hold now.
 * A pending range is drawn dashed when it differs from the plan (or there is no plan yet) and can be dragged.
 */
function RangeOverlay({ topogram, width, snapshot, drag, begin }: OverlayProps) {
  const series = snapshot.console.series ?? []
  return (
    <>
      {groupRanges(series).map((g) => (
        <RangeBox key={g.ids.join()} group={g} topogram={topogram} width={width} startMm={g.start_mm} endMm={g.end_mm} />
      ))}
      {pendingRanges(snapshot).map((g) => {
        const dragged = drag?.kind === 'edge' && drag.group.ids.join() === g.ids.join() ? drag : null
        const box = {
          group: g,
          topogram,
          width,
          startMm: dragged?.edge === 'start_mm' ? dragged.mm : g.start_mm,
          endMm: dragged?.edge === 'end_mm' ? dragged.mm : g.end_mm,
        }
        return (
          <g key={`pending-${g.ids.join()}`}>
            {(dragged || !isAccepted(g, series)) && <RangeBox {...box} pending />}
            <EdgeHandles {...box} begin={begin} />
          </g>
        )
      })}
    </>
  )
}

function LevelLine({ topogram: t, width, mm, pending = false }: { topogram: TopogramView; width: number; mm: number; pending?: boolean }) {
  const y = rowForMm(t, mm)
  return (
    <g data-testid={pending ? 'pending-level' : 'level'}>
      <line x1={0} x2={width} y1={y} y2={y} stroke={AMBER} strokeWidth={1.5} strokeDasharray={pending ? DASH : undefined} />
      <text x={width - 3} y={pending ? y + FONT + 1 : y - 2} fontSize={FONT} fill={AMBER} textAnchor="end">
        {pending ? `Level ${Math.round(mm)} mm, not taken yet` : `Tracking ${Math.round(mm)} mm`}
      </text>
    </g>
  )
}

/** The level of the monitoring slice already taken (solid) and, while that step can be edited, the level
 *  its field holds now: dashed when it differs, and it can be dragged. */
function LevelOverlay({ topogram, width, snapshot, drag, begin, interactive }: OverlayProps & { interactive: boolean }) {
  const taken = snapshot.console.tracking?.slice_mm ?? null
  const field = interactive ? editableNumber(snapshot, 'monitoring_slice', 'slice_mm') : null
  const pending = drag?.kind === 'level' ? drag.mm : field
  return (
    <>
      {taken != null && <LevelLine topogram={topogram} width={width} mm={taken} />}
      {pending != null && pending !== taken && <LevelLine topogram={topogram} width={width} mm={pending} pending />}
      {pending != null && canEditField(snapshot, 'monitoring_slice', 'slice_mm') && (
        <rect
          data-testid="handle-level"
          className="topogram__handle"
          x={0}
          width={width}
          y={rowForMm(topogram, pending) - HANDLE}
          height={HANDLE * 2}
          onPointerDown={begin({ kind: 'level', mm: pending })}
        />
      )}
    </>
  )
}

function ReferenceLines({ topogram: t, width, snapshot }: Pick<OverlayProps, 'topogram' | 'width' | 'snapshot'>) {
  return (
    <>
      {(snapshot.console.reference ?? []).map((r) => {
        const y = rowForMm(t, r.from_landmark_mm)
        return (
          <g key={r.name}>
            <line x1={0} x2={width} y1={y} y2={y} stroke={REF_STROKE} strokeDasharray="4 3" strokeWidth={1} />
            <text x={3} y={y - 2} fontSize={FONT} fill={REF_STROKE}>
              {r.label}
            </text>
          </g>
        )
      })}
    </>
  )
}

interface Props {
  topogram: TopogramView
  snapshot: Snapshot
  interactive: boolean
}

export default function TopogramViewer({ topogram: t, snapshot, interactive }: Props) {
  const { x0, width } = cropColumns(t.cols)
  const win = rowWindow(t, plannedTopogramEndMm(snapshot, t.view))
  const canvasRef = useTopogramImage(t.image_url, x0, width, t.rows)
  const svgRef = useRef<SVGSVGElement>(null)
  const mmAt = (clientY: number): number => {
    const rect = svgRef.current?.getBoundingClientRect()
    const frac = rect && rect.height > 0 && Number.isFinite(clientY) ? (clientY - rect.top) / rect.height : 0
    return Math.round(clampToRevealed(t, mmForRow(t, rowAtFraction(win ?? { top: 0, rows: t.rows }, frac))))
  }
  const { drag, rejection, begin, move, release, cancel } = useDrag(snapshot, svgRef, mmAt)
  if (!win) return <div className="viewer__empty">Not acquired yet</div>
  const overlay = { topogram: t, width, snapshot, drag, begin }
  const canvasStyle = { position: 'absolute', left: 0, width: '100%', height: `${(t.rows / win.rows) * 100}%`, top: `${(-win.top / win.rows) * 100}%` } as const
  return (
    <div>
      <div className="topogram" style={{ aspectRatio: `${width} / ${win.rows}`, overflow: 'hidden' }}>
        <canvas ref={canvasRef} width={width} height={t.rows} aria-label={`${t.view} topogram`} style={canvasStyle} />
        <svg ref={svgRef} viewBox={`0 ${win.top} ${width} ${win.rows}`} preserveAspectRatio="none" onPointerMove={move} onPointerUp={release} onPointerCancel={cancel}>
          <rect x={0} y={0} width={width} height={Math.max(0, t.revealed_from_row)} fill="#0c1b24" opacity={0.92} />
          <rect x={0} y={t.revealed_to_row} width={width} height={Math.max(0, t.rows - t.revealed_to_row)} fill="#0c1b24" opacity={0.92} />
          <ReferenceLines topogram={t} width={width} snapshot={snapshot} />
          {interactive && <RangeOverlay {...overlay} />}
          <LevelOverlay {...overlay} interactive={interactive} />
        </svg>
      </div>
      {rejection && (
        <p role="alert" className="viewer__error">
          {rejection}
        </p>
      )}
    </div>
  )
}

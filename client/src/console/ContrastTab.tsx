import { useState } from 'react'
import type { InjectorView, Snapshot, TrackingSample, TrackingView } from '../api/types.gen'
import { useSession } from '../store/session'
import { canEditField, editableNumber, formatClock, trackingFov } from './topogramMath'

const AMBER = '#c78a12'
const CURVE = { w: 300, h: 130, left: 34, right: 8, top: 10, bottom: 20 }

function InjectorSummary({ injector }: { injector: InjectorView | null | undefined }) {
  if (!injector) return <p className="panel__note">No injector connected.</p>
  const over = injector.pressure_psi >= injector.pressure_limit_psi
  return (
    <dl className="console__facts">
      <dt>State</dt>
      <dd>{injector.state}</dd>
      <dt>Contrast</dt>
      <dd>
        {injector.contrast_ml} mL loaded, {injector.injected_contrast_ml} mL given
      </dd>
      <dt>Saline</dt>
      <dd>
        {injector.saline_ml} mL loaded, {injector.injected_saline_ml} mL given
      </dd>
      <dt>Flow</dt>
      <dd>{injector.flow_ml_s} mL/s</dd>
      <dt>Pressure</dt>
      <dd className={over ? 'console__alert' : undefined}>
        {injector.pressure_psi} / {injector.pressure_limit_psi} psi
        <span className="console__tag" title="No published pressure model or default limit was found: both are assumptions of the simulator.">
          assumed
        </span>
      </dd>
    </dl>
  )
}

interface Region {
  x: number
  y: number
  r: number
}

/**
 * The region the fields of "Place ROI" hold now, while that step can be edited and it differs from the
 * accepted region: a click moves this one, and performing the step accepts it.
 */
function pendingRegion(snapshot: Snapshot, tracking: TrackingView): Region | null {
  const [x, y, r] = ['roi_x_mm', 'roi_y_mm', 'roi_r_mm'].map((key) => editableNumber(snapshot, 'place_roi', key))
  if (x == null || y == null || r == null) return null
  const accepted = tracking.baseline_hu != null && x === tracking.roi_x_mm && y === tracking.roi_y_mm && r === tracking.roi_r_mm
  return accepted ? null : { x, y, r }
}

function TrackingImage({ snapshot, tracking }: { snapshot: Snapshot; tracking: TrackingView }) {
  const send = useSession((s) => s.send)
  const [rejection, setRejection] = useState<string | null>(null)
  const fov = trackingFov(snapshot.console.series ?? [])
  const editable =
    canEditField(snapshot, 'place_roi', 'roi_x_mm') && canEditField(snapshot, 'place_roi', 'roi_y_mm')
  const points = snapshot.console.reference_points ?? []
  const pending = pendingRegion(snapshot, tracking)
  if (!tracking.image_url || fov <= 0) return <div className="viewer viewer__empty">No tracking image yet</div>

  const onClick = async (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    if (!editable || rect.width <= 0 || rect.height <= 0) return
    const x = ((e.clientX - rect.left) / rect.width - 0.5) * fov
    const y = ((e.clientY - rect.top) / rect.height - 0.5) * fov
    setRejection(null)
    const first = await send({ type: 'set_field', step_id: 'place_roi', key: 'roi_x_mm', value: Math.round(x) })
    if (!first.ok) return setRejection(first.error ?? 'The region was not moved')
    const second = await send({ type: 'set_field', step_id: 'place_roi', key: 'roi_y_mm', value: Math.round(y) })
    if (!second.ok) setRejection(second.error ?? 'The region was only moved sideways')
  }
  const unit = fov / 100
  return (
    <div className="viewer">
      <div className="topogram" onClick={onClick} style={{ cursor: editable ? 'crosshair' : 'default' }}>
        <img src={tracking.image_url} alt="Tracking image" style={{ width: '100%', display: 'block' }} />
        <svg viewBox={`${-fov / 2} ${-fov / 2} ${fov} ${fov}`} aria-hidden="true">
          {tracking.baseline_hu != null && (
            <circle data-testid="roi" cx={tracking.roi_x_mm} cy={tracking.roi_y_mm} r={tracking.roi_r_mm} fill="none" stroke={AMBER} strokeWidth={unit * 0.8} />
          )}
          {pending && (
            <circle data-testid="pending-roi" cx={pending.x} cy={pending.y} r={pending.r} fill="none" stroke={AMBER} strokeWidth={unit * 0.8} strokeDasharray={`${unit * 2} ${unit * 1.5}`} />
          )}
          {points.map((p) => (
            <g key={p.name}>
              <circle cx={p.x_mm} cy={p.y_mm} r={unit * 1.2} fill="#8fa8b5" />
              <text x={p.x_mm + unit * 2} y={p.y_mm} fontSize={unit * 3.5} fill="#cfe3ec">
                {p.label}
              </text>
            </g>
          ))}
        </svg>
      </div>
      {pending && <p className="panel__note">The dashed circle is not accepted yet: perform "Place ROI" to measure its baseline.</p>}
      {rejection && (
        <p role="alert" className="console__alert">
          {rejection}
        </p>
      )}
    </div>
  )
}

function scaleFor(samples: TrackingSample[], trigger: number | null) {
  const hus = samples.map((s) => s.hu).concat(trigger ?? [])
  const ts = samples.map((s) => s.t_s)
  const [t0, t1] = [Math.min(...ts), Math.max(...ts, Math.min(...ts) + 1)]
  const [lo, hi] = [Math.min(...hus) - 10, Math.max(...hus) + 10]
  const plotW = CURVE.w - CURVE.left - CURVE.right
  const plotH = CURVE.h - CURVE.top - CURVE.bottom
  return {
    x: (t: number) => CURVE.left + ((t - t0) / (t1 - t0)) * plotW,
    y: (hu: number) => CURVE.top + (1 - (hu - lo) / (hi - lo)) * plotH,
    t0,
    t1,
    lo,
    hi,
  }
}

function TrackingCurve({ tracking }: { tracking: TrackingView }) {
  const samples = tracking.samples ?? []
  const trigger = tracking.baseline_hu == null ? null : tracking.baseline_hu + tracking.threshold_hu
  if (samples.length === 0) return <p className="panel__note">No monitoring samples yet.</p>
  const sc = scaleFor(samples, trigger)
  const path = samples.map((s) => `${sc.x(s.t_s)},${sc.y(s.hu)}`).join(' ')
  const axisY = CURVE.h - CURVE.bottom
  return (
    <svg className="curve" viewBox={`0 0 ${CURVE.w} ${CURVE.h}`} role="img" aria-label="Bolus tracking curve">
      <line x1={CURVE.left} x2={CURVE.left} y1={CURVE.top} y2={axisY} stroke="#9fb1bc" />
      <line x1={CURVE.left} x2={CURVE.w - CURVE.right} y1={axisY} y2={axisY} stroke="#9fb1bc" />
      <text x={CURVE.left - 3} y={CURVE.top + 6} fontSize={8} textAnchor="end" fill="#5a6c78">
        {Math.round(sc.hi)}
      </text>
      <text x={CURVE.left - 3} y={axisY} fontSize={8} textAnchor="end" fill="#5a6c78">
        {Math.round(sc.lo)}
      </text>
      <text x={CURVE.left} y={CURVE.h - 6} fontSize={8} fill="#5a6c78">
        {formatClock(sc.t0)}
      </text>
      <text x={CURVE.w - CURVE.right} y={CURVE.h - 6} fontSize={8} textAnchor="end" fill="#5a6c78">
        {formatClock(sc.t1)}
      </text>
      {trigger != null && (
        <g>
          <line x1={CURVE.left} x2={CURVE.w - CURVE.right} y1={sc.y(trigger)} y2={sc.y(trigger)} stroke={AMBER} strokeDasharray="4 3" />
          <text x={CURVE.left + 4} y={sc.y(trigger) - 3} fontSize={8} fill={AMBER}>
            {`Trigger ${Math.round(trigger)} HU`}
          </text>
        </g>
      )}
      <polyline points={path} fill="none" stroke="#166b78" strokeWidth={1.6} />
    </svg>
  )
}

export default function ContrastTab({ snapshot }: { snapshot: Snapshot }) {
  const send = useSession((s) => s.send)
  const tracking = snapshot.console.tracking
  const manualOk = tracking?.state === 'monitoring' || tracking?.state === 'manual'
  return (
    <div>
      <h3>Injector</h3>
      <InjectorSummary injector={snapshot.injector} />
      <h3>Bolus tracking{tracking ? `, ${tracking.state.replace('_', ' ')}` : ''}</h3>
      {tracking ? (
        <>
          <TrackingImage snapshot={snapshot} tracking={tracking} />
          <TrackingCurve tracking={tracking} />
        </>
      ) : (
        <p className="panel__note">Tracking is not set up yet.</p>
      )}
      {manualOk && (
        <p>
          <button className="btn" onClick={() => void send({ type: 'manual_start' })}>
            Start scan manually
          </button>
        </p>
      )}
    </div>
  )
}

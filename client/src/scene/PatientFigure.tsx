import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import type { Snapshot } from '../api/types.gen'
import { Figure, ellipsoid, limb, makePosed, type PartSpec, type Posed } from './bodyParts'
import { lerpRig, lyingRig, sittingRig, standingRig, walkGoal, type JointName, type Rig } from './figureRig'
import { PERSON_SPOTS, type Vec3 } from './layout'
import { SurfaceMarks } from './SurfaceMarks'
import { useSlotModel } from './useSlotModel'
import { POSE_PRIORITY, useEasedRef, type Live } from './useSmoothed'
import { add, lerp3, sub, unit } from './vec'

const MM = 0.001
const REFERENCE_STATURE_M = 1.72
const BLEND_RATE = 2.2
const VISIBLE_WALK = 0.01

type Stage = Snapshot['pose']['stage']

/** How far each pose blend should be for a stage: walked in, sitting, lying. */
export function stageTargets(stage: Stage): { walk: number; sit: number; lie: number } {
  switch (stage) {
    case 'away':
    case 'leaving':
      return { walk: 0, sit: 0, lie: 0 }
    case 'entering':
    case 'standing':
      return { walk: 1, sit: 0, lie: 0 }
    case 'sitting':
      return { walk: 1, sit: 1, lie: 0 }
    case 'lying':
      return { walk: 1, sit: 0, lie: 1 }
  }
}

function currentRig(s: Snapshot, walk: number, sit: number, lie: number): Rig {
  const stature = s.pose.stature_mm * MM
  const { patientDoor, patientStand } = PERSON_SPOTS
  const pos = lerp3(patientDoor, patientStand, walk)
  const pathYaw = Math.atan2(patientStand[0] - patientDoor[0], patientStand[2] - patientDoor[2])
  const arrived = Math.min(1, Math.max(0, (walk - 0.85) / 0.15))
  const yaw = pathYaw + (Math.PI / 2 - pathYaw) * arrived
  const stand = standingRig(stature, pos, yaw)
  const upright = sit > 0.001 ? lerpRig(stand, sittingRig(s), sit) : stand
  return lie > 0.001 ? lerpRig(upright, lyingRig(s), lie) : upright
}

const joint = (name: JointName) => (p: Posed): Vec3 => p.rig[name]

function armParts(side: 'L' | 'R', k: number): PartSpec[] {
  const hand = (p: Posed) => add(p.rig[`wrist${side}`], unit(sub(p.rig[`wrist${side}`], p.rig[`elbow${side}`])), 0.1 * k)
  return [
    limb(joint(`shoulder${side}`), joint(`elbow${side}`), 0.052 * k, 0.043 * k, 'gown'),
    limb(joint(`elbow${side}`), joint(`wrist${side}`), 0.04 * k, 0.03 * k, 'skin'),
    limb(joint(`wrist${side}`), hand, 0.03 * k, 0.022 * k, 'skin'),
  ]
}

function legParts(side: 'L' | 'R', k: number): PartSpec[] {
  return [
    limb(joint(`hip${side}`), joint(`knee${side}`), 0.088 * k, 0.06 * k, 'pants'),
    limb(joint(`knee${side}`), joint(`ankle${side}`), 0.056 * k, 0.04 * k, 'pants'),
    limb(joint(`ankle${side}`), joint(`toe${side}`), 0.042 * k, 0.032 * k, 'skin'),
  ]
}

function patientParts(k: number): PartSpec[] {
  const h = k * REFERENCE_STATURE_M
  return [
    ellipsoid((p) => add(p.rig.chest, p.axes[2], 0.004 * p.breath), (p) => [0.17 * k, 0.12 * h, 0.11 * k * (1 + 0.07 * p.breath)], 'gown'),
    ellipsoid((p) => lerp3(p.rig.chest, p.rig.pelvis, 0.62), () => [0.15 * k, 0.09 * h, 0.095 * k], 'gown'),
    ellipsoid(joint('pelvis'), () => [0.16 * k, 0.07 * h, 0.1 * k], 'pants'),
    limb(joint('shoulderR'), joint('shoulderL'), 0.055 * k, 0.055 * k, 'gown'),
    limb(joint('neck'), (p) => add(p.rig.head, p.axes[1], -0.04 * k), 0.048 * k, 0.045 * k, 'skin'),
    ellipsoid(joint('head'), () => [0.078 * k, 0.065 * h, 0.095 * k], 'skin'),
    ellipsoid((p) => add(add(p.rig.head, p.axes[1], 0.02 * k), p.axes[2], -0.018 * k), () => [0.081 * k, 0.062 * h, 0.093 * k], 'hair'),
    ...armParts('L', k),
    ...armParts('R', k),
    ...legParts('L', k),
    ...legParts('R', k),
  ]
}

interface PatientProps {
  sm: Live<Snapshot>
  stage: Stage
  statureMm: number
  marks: Snapshot['pose']['surface_marks']
}

/** The patient: walks in, stands beside the table, sits on its edge or lies on it. Moves by frame callback. */
export default function PatientFigure({ sm, stage, statureMm, marks }: PatientProps) {
  const slot = useSlotModel('patient')
  const target = stageTargets(stage)
  const sit = useEasedRef(target.sit, BLEND_RATE)
  const lie = useEasedRef(target.lie, BLEND_RATE)
  const walk = useEasedRef(() => walkGoal(stage, lie.current, sit.current), BLEND_RATE)
  const posed = useRef<Posed | null>(null)
  useFrame(() => {
    if (walk.current < VISIBLE_WALK) {
      posed.current = null
      return
    }
    const s = sm.current
    const rig = currentRig(s, walk.current, sit.current, lie.current)
    posed.current = makePosed(rig, lie.current > 0.5 ? s.pose.breath : 0, lie.current)
  }, POSE_PRIORITY)
  const k = (statureMm * MM) / REFERENCE_STATURE_M
  const parts = useMemo(() => patientParts(k), [k])
  if (slot) return <primitive object={slot} />
  return (
    <>
      <Figure parts={parts} posed={posed} />
      {stage === 'lying' && <SurfaceMarks sm={sm} posed={posed} marks={marks ?? []} statureMm={statureMm} />}
    </>
  )
}

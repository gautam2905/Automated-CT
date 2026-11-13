import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import type { Snapshot } from '../api/types.gen'
import { Figure, ellipsoid, limb, makePosed, type PartSpec, type Posed } from './bodyParts'
import { standingRig, type JointName } from './figureRig'
import { technologistFacing, technologistSpot } from './transforms'
import { useSlotModel } from './useSlotModel'
import { POSE_PRIORITY, angleDelta, easeToward, type Live } from './useSmoothed'
import { add } from './vec'
import type { Vec3 } from './layout'

const STATURE_M = 1.74
const K = STATURE_M / 1.72
const WALK_RATE = 1.6
const TURN_RATE = 6
const WALKING_DISTANCE_M = 0.2

const joint = (name: JointName) => (p: Posed): Vec3 => p.rig[name]

function techParts(): PartSpec[] {
  const parts: PartSpec[] = [
    ellipsoid(joint('chest'), () => [0.18 * K, 0.21, 0.115 * K], 'scrubs'),
    ellipsoid(joint('pelvis'), () => [0.17 * K, 0.13, 0.11 * K], 'scrubsDark'),
    limb(joint('shoulderR'), joint('shoulderL'), 0.058 * K, 0.058 * K, 'scrubs'),
    limb(joint('neck'), joint('head'), 0.048 * K, 0.045 * K, 'skin'),
    ellipsoid(joint('head'), () => [0.078 * K, 0.112, 0.095 * K], 'skin'),
    ellipsoid((p) => add(add(p.rig.head, p.axes[1], 0.03), p.axes[2], -0.02), () => [0.081 * K, 0.1, 0.093 * K], 'techHair'),
  ]
  for (const side of ['L', 'R'] as const) {
    parts.push(
      limb(joint(`shoulder${side}`), joint(`elbow${side}`), 0.052 * K, 0.044 * K, 'scrubs'),
      limb(joint(`elbow${side}`), joint(`wrist${side}`), 0.04 * K, 0.03 * K, 'skin'),
      limb(joint(`hip${side}`), joint(`knee${side}`), 0.088 * K, 0.062 * K, 'scrubsDark'),
      limb(joint(`knee${side}`), joint(`ankle${side}`), 0.058 * K, 0.042 * K, 'scrubsDark'),
      limb(joint(`ankle${side}`), joint(`toe${side}`), 0.046 * K, 0.036 * K, 'shoes'),
    )
  }
  return parts
}

/** The technologist at the spot for `room.technologist_at`; glides between spots. Moves by frame callback. */
export default function Technologist({ target }: { target: Live<Snapshot> }) {
  const slot = useSlotModel('technologist')
  const parts = useMemo(techParts, [])
  const posed = useRef<Posed | null>(null)
  const state = useRef<{ x: number; z: number; yaw: number } | null>(null)
  useFrame((_, dt) => {
    const t = target.current
    const spot = technologistSpot(t)
    const st = (state.current ??= { x: spot[0], z: spot[2], yaw: technologistFacing(t) })
    st.x = easeToward(st.x, spot[0], WALK_RATE, dt)
    st.z = easeToward(st.z, spot[2], WALK_RATE, dt)
    const toSpot = Math.hypot(spot[0] - st.x, spot[2] - st.z)
    const facing = toSpot > WALKING_DISTANCE_M ? Math.atan2(spot[0] - st.x, spot[2] - st.z) : technologistFacing(t)
    st.yaw += angleDelta(st.yaw, facing) * (1 - Math.exp(-TURN_RATE * Math.min(dt, 0.1)))
    posed.current = makePosed(standingRig(STATURE_M, [st.x, 0, st.z], st.yaw), 0, 0)
  }, POSE_PRIORITY)
  if (slot) return <primitive object={slot} />
  return <Figure parts={parts} posed={posed} />
}

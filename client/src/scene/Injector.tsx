import { useFrame } from '@react-three/fiber'
import { memo, useEffect, useRef } from 'react'
import { CatmullRomCurve3, TubeGeometry, Vector3, type Mesh } from 'three'
import type { InjectorView, Snapshot } from '../api/types.gen'
import { lyingRig } from './figureRig'
import { PERSON_SPOTS, type Vec3 } from './layout'
import { Box, Matte } from './shellParts'
import { useSlotModel } from './useSlotModel'
import { POSE_PRIORITY, useEasedRef, type Live } from './useSmoothed'

// Visual syringe capacities. The engine does not send them, so the fill level is only a picture.
const CONTRAST_CAPACITY_ML = 200
const SALINE_CAPACITY_ML = 100
const BARREL_LENGTH = 0.3
const BARREL_RADIUS = 0.032
const HEAD_Y = 1.45
const SYRINGE_TILT = 0.3
const FILL_RATE = 8
/** The IV line is rebuilt only when its arm end moves further than this (metres). */
const LINE_REBUILD_M = 0.001
const STATE_LED: Record<InjectorView['state'], string> = {
  unloaded: '#6b7780',
  loaded: '#d9b53a',
  purged: '#d9b53a',
  connected: '#3a9fd9',
  armed: '#e08a2b',
  injecting: '#35d27b',
  done: '#6b7780',
}

function Syringe({ z, fillMl, capacityMl, colour }: { z: number; fillMl: number; capacityMl: number; colour: string }) {
  const fill = useEasedRef(Math.min(1, Math.max(0, fillMl / capacityMl)), FILL_RATE)
  const liquid = useRef<Mesh>(null)
  useFrame(() => {
    const len = fill.current * BARREL_LENGTH
    if (!liquid.current) return
    liquid.current.visible = len > 0.002
    liquid.current.scale.set(1, Math.max(len, 1e-4), 1)
    liquid.current.position.set(0, BARREL_LENGTH - len / 2, 0)
  })
  return (
    <group position={[-0.17, HEAD_Y, z]} rotation={[0, 0, Math.PI / 2 + SYRINGE_TILT]}>
      <mesh position={[0, BARREL_LENGTH / 2, 0]}>
        <cylinderGeometry args={[BARREL_RADIUS, BARREL_RADIUS, BARREL_LENGTH, 20, 1, true]} />
        <meshPhysicalMaterial color="#dfeef5" transparent opacity={0.28} roughness={0.05} side={2} depthWrite={false} />
      </mesh>
      <mesh ref={liquid}>
        <cylinderGeometry args={[BARREL_RADIUS * 0.92, BARREL_RADIUS * 0.92, 1, 20]} />
        <meshStandardMaterial color={colour} roughness={0.2} transparent opacity={0.9} />
      </mesh>
      <mesh position={[0, 0.01, 0]}>
        <cylinderGeometry args={[BARREL_RADIUS * 0.95, BARREL_RADIUS * 0.95, 0.02, 20]} />
        <meshStandardMaterial color="#2c353b" roughness={0.5} />
      </mesh>
    </group>
  )
}

/** Syringe tip of the contrast barrel, relative to the stand origin. */
function contrastTip(): Vec3 {
  return [-0.17 - Math.cos(SYRINGE_TILT) * BARREL_LENGTH, HEAD_Y - Math.sin(SYRINGE_TILT) * BARREL_LENGTH, -0.05]
}

/** Line from the syringe to the patient's elbow. Follows the table through the eased snapshot. */
function IvLine({ sm, target }: { sm: Live<Snapshot>; target: Live<Snapshot> }) {
  const mesh = useRef<Mesh>(null)
  const lastEnd = useRef<Vector3 | null>(null)
  useEffect(() => () => mesh.current?.geometry.dispose(), [])
  useFrame(() => {
    const m = mesh.current
    if (!m) return
    const t = target.current
    m.visible = t.pose.iv_connected && t.pose.stage === 'lying'
    if (!m.visible) return
    const rig = lyingRig(sm.current)
    const elbow = rig.elbowL[0] > rig.elbowR[0] ? rig.elbowL : rig.elbowR
    const end = new Vector3(...elbow)
    if (lastEnd.current && lastEnd.current.distanceTo(end) < LINE_REBUILD_M) return
    lastEnd.current = end
    const tip = contrastTip()
    const start = new Vector3(PERSON_SPOTS.injector[0] + tip[0], tip[1], PERSON_SPOTS.injector[2] + tip[2])
    const sag = new Vector3().lerpVectors(start, end, 0.5).add(new Vector3(0, -0.3, 0))
    m.geometry.dispose()
    m.geometry = new TubeGeometry(new CatmullRomCurve3([start, sag, end]), 24, 0.004, 6, false)
  }, POSE_PRIORITY)
  return (
    <mesh ref={mesh} visible={false}>
      <meshStandardMaterial color="#cfe9f2" roughness={0.2} transparent opacity={0.85} />
    </mesh>
  )
}

interface InjectorProps {
  sm: Live<Snapshot>
  target: Live<Snapshot>
  present: boolean
  state: InjectorView['state']
  contrastMl: number
  salineMl: number
}

/** Power injector on a floor stand; the line to the patient's arm shows when the IV is connected. */
function InjectorImpl({ sm, target, present, state, contrastMl, salineMl }: InjectorProps) {
  const slot = useSlotModel('injector')
  if (slot) return <primitive object={slot} />
  if (!present) return null
  return (
    <group>
      <group position={PERSON_SPOTS.injector}>
        <mesh position={[0, 0.03, 0]} castShadow>
          <cylinderGeometry args={[0.3, 0.32, 0.05, 32]} />
          <meshStandardMaterial color="#4a565e" roughness={0.5} metalness={0.4} />
        </mesh>
        <mesh position={[0, 0.75, 0]} castShadow>
          <cylinderGeometry args={[0.03, 0.03, 1.4, 16]} />
          <meshStandardMaterial color="#a9b3ba" roughness={0.3} metalness={0.7} />
        </mesh>
        <Box position={[0, HEAD_Y, 0]} size={[0.34, 0.2, 0.24]}>
          <meshPhysicalMaterial color="#e9edef" roughness={0.35} clearcoat={0.6} />
        </Box>
        <mesh position={[-0.171, HEAD_Y + 0.02, 0]} rotation={[0, -Math.PI / 2, 0]}>
          <planeGeometry args={[0.16, 0.07]} />
          <meshStandardMaterial color={STATE_LED[state]} emissive={STATE_LED[state]} emissiveIntensity={0.9} />
        </mesh>
        <Syringe z={-0.05} fillMl={contrastMl} capacityMl={CONTRAST_CAPACITY_ML} colour="#e5cf6a" />
        <Syringe z={0.05} fillMl={salineMl} capacityMl={SALINE_CAPACITY_ML} colour="#8fd0f2" />
        <Box position={[0, HEAD_Y - 0.13, 0]} size={[0.1, 0.06, 0.1]}>
          <Matte colour="#2c353b" />
        </Box>
      </group>
      <IvLine sm={sm} target={target} />
    </group>
  )
}

export default memo(InjectorImpl)

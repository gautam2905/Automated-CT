import { useFrame } from '@react-three/fiber'
import { memo, useEffect, useMemo, useRef } from 'react'
import { AdditiveBlending, DoubleSide, ExtrudeGeometry, Shape, type Group } from 'three'
import type { Snapshot } from '../api/types.gen'
import type { Live } from './useSmoothed'

const MM = 0.001
const LASER_RED = '#ff2a2a'
const FAN_APEX_R = 0.78
const FAN_DETECTOR_R = 0.7
const FAN_HALF_SPAN = 0.74
const FAN_THICKNESS = 0.02

function useFanGeometry() {
  const geo = useMemo(() => {
    const shape = new Shape()
    const x = Math.sin(FAN_HALF_SPAN) * FAN_DETECTOR_R
    const y = -Math.cos(FAN_HALF_SPAN) * FAN_DETECTOR_R
    shape.moveTo(0, FAN_APEX_R)
    shape.lineTo(-x, y)
    shape.lineTo(x, y)
    shape.closePath()
    const g = new ExtrudeGeometry(shape, { depth: FAN_THICKNESS, bevelEnabled: false })
    g.translate(0, 0, -FAN_THICKNESS / 2)
    return g
  }, [])
  useEffect(() => () => geo.dispose(), [geo])
  return geo
}

/** The X-ray fan in the scan plane, turning with the tube. Rendered only while the beam is on. */
export function FanBeam({ sm, beamOn, isoMm }: { sm: Live<Snapshot>; beamOn: boolean; isoMm: number }) {
  const geo = useFanGeometry()
  const group = useRef<Group>(null)
  useFrame(() => {
    if (group.current) group.current.rotation.z = (-sm.current.scanner.tube_angle_deg * Math.PI) / 180
  })
  if (!beamOn) return null
  return (
    <group ref={group} position={[0, isoMm * MM, 0]}>
      <mesh geometry={geo} renderOrder={3}>
        <meshBasicMaterial color="#ffc94d" transparent opacity={0.4} blending={AdditiveBlending} depthWrite={false} side={DoubleSide} />
      </mesh>
    </group>
  )
}

function LaserLine({ position, size }: { position: [number, number, number]; size: [number, number, number] }) {
  return (
    <mesh position={position}>
      <boxGeometry args={size} />
      <meshBasicMaterial color={LASER_RED} toneMapped={false} />
    </mesh>
  )
}

/** Positioning laser light: an axial sheet plus the coronal and sagittal lines in the laser plane. */
function LaserSheetsImpl({ lasersOn, laserZMm, isoMm }: { lasersOn: boolean; laserZMm: number; isoMm: number }) {
  if (!lasersOn) return null
  const z = laserZMm * MM
  const iso = isoMm * MM
  return (
    <group>
      <mesh position={[0, iso, z]} renderOrder={3}>
        <planeGeometry args={[1.1, 0.9]} />
        <meshBasicMaterial color={LASER_RED} transparent opacity={0.05} depthWrite={false} side={DoubleSide} blending={AdditiveBlending} />
      </mesh>
      <LaserLine position={[0, iso, z]} size={[1.1, 0.006, 0.006]} />
      <LaserLine position={[0, iso + 0.3, z]} size={[0.006, 0.6, 0.006]} />
      <LaserLine position={[0, iso - 0.38, z]} size={[0.5, 0.006, 0.006]} />
    </group>
  )
}

export const LaserSheets = memo(LaserSheetsImpl)

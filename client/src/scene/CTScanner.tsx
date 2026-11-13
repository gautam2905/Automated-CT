import { useFrame } from '@react-three/fiber'
import { memo, useEffect, useMemo, useRef } from 'react'
import { BackSide, DoubleSide, ExtrudeGeometry, Path, Shape, type Group, type Material, type Mesh } from 'three'
import type { Snapshot } from '../api/types.gen'
import { GANTRY } from './layout'
import { drawCanvasTexture } from './shellParts'
import { useSlotModel } from './useSlotModel'
import { useEasedRef, type Live } from './useSmoothed'

const SEE_THROUGH_OPACITY = 0.14
const CORNER_RADIUS = 0.2
const ROTOR_OUTER_R = 0.84
const TUBE_R = 0.78
const DETECTOR_R = 0.7
const DETECTOR_HALF_SPAN = 0.74

function roundedRect(shape: Shape, x0: number, y0: number, x1: number, y1: number, r: number) {
  shape.moveTo(x0 + r, y0)
  shape.lineTo(x1 - r, y0)
  shape.quadraticCurveTo(x1, y0, x1, y0 + r)
  shape.lineTo(x1, y1 - r)
  shape.quadraticCurveTo(x1, y1, x1 - r, y1)
  shape.lineTo(x0 + r, y1)
  shape.quadraticCurveTo(x0, y1, x0, y1 - r)
  shape.lineTo(x0, y0 + r)
  shape.quadraticCurveTo(x0, y0, x0 + r, y0)
}

/** Gantry cover: a rounded slab with the bore cut through it, centred on the isocentre. */
function useHousingGeometry(boreR: number, isoY: number) {
  const geo = useMemo(() => {
    const shape = new Shape()
    roundedRect(shape, -GANTRY.width / 2, 0.02 - isoY, GANTRY.width / 2, GANTRY.height - isoY, CORNER_RADIUS)
    const hole = new Path()
    hole.absarc(0, 0, boreR, 0, Math.PI * 2, true)
    shape.holes.push(hole)
    const depth = GANTRY.halfDepth * 2 - 0.04
    const g = new ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 3, curveSegments: 64 })
    g.translate(0, 0, -depth / 2)
    return g
  }, [boreR, isoY])
  useEffect(() => () => geo.dispose(), [geo])
  return geo
}

function useRingGeometry(inner: number, outer: number) {
  const geo = useMemo(() => {
    const shape = new Shape()
    shape.absarc(0, 0, outer, 0, Math.PI * 2, false)
    const hole = new Path()
    hole.absarc(0, 0, inner, 0, Math.PI * 2, true)
    shape.holes.push(hole)
    const g = new ExtrudeGeometry(shape, { depth: 0.22, bevelEnabled: false, curveSegments: 64 })
    g.translate(0, 0, -0.11)
    return g
  }, [inner, outer])
  useEffect(() => () => geo.dispose(), [geo])
  return geo
}

/** Tube, collimator and detector arc: they turn with the tube angle (0 = tube at top). */
function Rotor({ boreR, rotorRef }: { boreR: number; rotorRef: React.RefObject<Group | null> }) {
  const inner = useRingGeometry(boreR + 0.03, boreR + 0.1)
  const outer = useRingGeometry(ROTOR_OUTER_R - 0.09, ROTOR_OUTER_R)
  return (
    <group ref={rotorRef}>
      <mesh geometry={inner}>
        <meshStandardMaterial color="#9aa6ad" roughness={0.45} metalness={0.5} />
      </mesh>
      <mesh geometry={outer}>
        <meshStandardMaterial color="#9aa6ad" roughness={0.45} metalness={0.5} />
      </mesh>
      <mesh position={[0, 0, -0.1]}>
        <ringGeometry args={[boreR + 0.1, ROTOR_OUTER_R - 0.09, 64]} />
        <meshStandardMaterial color="#c3ccd2" transparent opacity={0.3} side={DoubleSide} depthWrite={false} />
      </mesh>
      <mesh position={[0, TUBE_R, 0]}>
        <boxGeometry args={[0.3, 0.2, 0.2]} />
        <meshStandardMaterial color="#c8a64a" roughness={0.3} metalness={0.8} />
      </mesh>
      <mesh position={[0, TUBE_R - 0.15, 0]}>
        <boxGeometry args={[0.16, 0.1, 0.1]} />
        <meshStandardMaterial color="#2c353b" roughness={0.5} metalness={0.5} />
      </mesh>
      <mesh position={[0, 0, 0]} rotation={[0, 0, -Math.PI / 2 - DETECTOR_HALF_SPAN]} scale={[1, 1, 4]}>
        <torusGeometry args={[DETECTOR_R, 0.03, 8, 48, DETECTOR_HALF_SPAN * 2]} />
        <meshStandardMaterial color="#5fb7ae" roughness={0.35} metalness={0.4} />
      </mesh>
    </group>
  )
}

function Plaque({ text, y }: { text: string; y: number }) {
  const map = useMemo(
    () =>
      drawCanvasTexture(256, 64, (g) => {
        g.fillStyle = '#1c262c'
        g.fillRect(0, 0, 256, 64)
        g.fillStyle = '#dfe8ec'
        g.font = '600 30px sans-serif'
        g.textAlign = 'center'
        g.textBaseline = 'middle'
        g.fillText(text, 128, 34)
      }),
    [text],
  )
  useEffect(() => () => map.dispose(), [map])
  return (
    <mesh position={[-0.75, y, GANTRY.halfDepth + 0.0005]}>
      <planeGeometry args={[0.36, 0.09]} />
      <meshBasicMaterial map={map} />
    </mesh>
  )
}

interface ScannerProps {
  sm: Live<Snapshot>
  boreMm: number
  isoMm: number
  model: string
  beamOn: boolean
}

const SOLID_OPACITY = 0.98

/**
 * The CT gantry: housing with the bore, and the rotor visible through it while the beam is on.
 * Opacity and rotor angle are applied each frame; React re-renders only when the beam switches.
 */
function CTScannerImpl({ sm, boreMm, isoMm, model, beamOn }: ScannerProps) {
  const slot = useSlotModel('ct_scanner')
  const boreR = boreMm / 2000
  const isoY = isoMm / 1000
  const opacity = useEasedRef(beamOn ? SEE_THROUGH_OPACITY : 1, 6)
  const housing = useHousingGeometry(boreR, isoY)
  const rotor = useRef<Group>(null)
  const housingMesh = useRef<Mesh>(null)
  const fadeMats = useRef<(Material | null)[]>([])
  const wasSolid = useRef(true)
  useFrame(() => {
    if (rotor.current) rotor.current.rotation.z = (-sm.current.scanner.tube_angle_deg * Math.PI) / 180
    const solid = opacity.current > SOLID_OPACITY
    for (const m of fadeMats.current) {
      if (!m) continue
      m.opacity = opacity.current
      m.depthWrite = solid
      if (m.transparent === solid) {
        m.transparent = !solid
        m.needsUpdate = true
      }
    }
    if (housingMesh.current && wasSolid.current !== solid) {
      housingMesh.current.castShadow = solid
      housingMesh.current.renderOrder = solid ? 0 : 2
    }
    wasSolid.current = solid
  })
  const fade = (i: number) => (m: Material | null) => void (fadeMats.current[i] = m)
  if (slot) return <primitive object={slot} />
  return (
    <group position={[0, isoY, 0]}>
      <Rotor boreR={boreR} rotorRef={rotor} />
      <mesh ref={housingMesh} geometry={housing} castShadow receiveShadow>
        <meshPhysicalMaterial ref={fade(0)} color="#eef0f2" roughness={0.32} metalness={0} clearcoat={0.8} clearcoatRoughness={0.12} />
      </mesh>
      <mesh position={[0, 0, GANTRY.halfDepth + 0.002]}>
        <torusGeometry args={[boreR + 0.045, 0.012, 12, 96]} />
        <meshStandardMaterial ref={fade(1)} color="#38c3d6" emissive="#38c3d6" emissiveIntensity={0.9} />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[boreR - 0.004, boreR - 0.004, GANTRY.halfDepth * 2 - 0.02, 64, 1, true]} />
        <meshStandardMaterial ref={fade(2)} color="#c4ccd1" roughness={0.45} side={BackSide} />
      </mesh>
      <mesh position={[0.72, 0.35, GANTRY.halfDepth + 0.001]}>
        <planeGeometry args={[0.26, 0.16]} />
        <meshStandardMaterial ref={fade(3)} color="#1c262c" roughness={0.2} metalness={0.3} emissive="#1d6f86" emissiveIntensity={0.6} />
      </mesh>
      <Plaque text={model} y={0.62} />
    </group>
  )
}

export default memo(CTScannerImpl)

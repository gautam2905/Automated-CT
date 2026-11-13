import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import { Group, Mesh, Quaternion, Sprite, Vector3 } from 'three'
import type { Snapshot, SurfaceMark } from '../api/types.gen'
import type { Posed } from './bodyParts'
import { surfacePoint, torsoFront } from './figureRig'
import { drawCanvasTexture } from './shellParts'
import { tableTop } from './transforms'
import type { Live } from './useSmoothed'
import { add } from './vec'

const MM = 0.001
const MARKS_VISIBLE_LIE = 0.9
const DOT_RADIUS = 0.011
const LEADER_RADIUS = 0.0018
/** Labels sit this far to the -x side of the table centre, clear of the patient. */
const LABEL_X = -0.62
const LABEL_BASE_ABOVE_TABLE = 0.26
const LABEL_ROW_STEP = 0.17
/** Labels are kept this far toward the table end, so they are never hidden inside the gantry. */
const LABEL_MIN_Z = 1.9
const LABEL_HEIGHT = 0.02
const LABEL_FONT_PX = 26
const Y_AXIS = new Vector3(0, 1, 0)

function useLabelTexture(text: string) {
  const { map, aspect } = useMemo(() => {
    const probe = document.createElement('canvas').getContext('2d')
    let w = 160
    if (probe) {
      probe.font = `${LABEL_FONT_PX}px sans-serif`
      w = Math.ceil(probe.measureText(text).width) + 16
    }
    const h = LABEL_FONT_PX + 8
    const tex = drawCanvasTexture(w, h, (g) => {
      g.fillStyle = 'rgba(24, 32, 38, 0.8)'
      g.fillRect(0, 0, w, h)
      g.fillStyle = '#ffd9a8'
      g.font = `${LABEL_FONT_PX}px sans-serif`
      g.textBaseline = 'middle'
      g.fillText(text, 8, h / 2 + 1)
    })
    return { map: tex, aspect: w / h }
  }, [text])
  useEffect(() => () => map.dispose(), [map])
  return { map, aspect }
}

interface MarkProps {
  mark: SurfaceMark
  row: number
  sm: Live<Snapshot>
  posed: Live<Posed | null>
  statureMm: number
}

/** An orange dot on the body, a thin leader line, and a compact label beside the table. */
function Mark({ mark, row, sm, posed, statureMm }: MarkProps) {
  const root = useRef<Group>(null)
  const dot = useRef<Mesh>(null)
  const leader = useRef<Mesh>(null)
  const label = useRef<Sprite>(null)
  const { map, aspect } = useLabelTexture(mark.label)
  useFrame(() => {
    const p = posed.current
    const visible = p !== null && p.lie > MARKS_VISIBLE_LIE
    if (root.current) root.current.visible = visible
    if (!visible || !dot.current || !leader.current || !label.current) return
    const pt = add(surfacePoint(p.rig, mark.z_body_mm, statureMm * MM), torsoFront(p.rig), 0.006)
    const anchor = new Vector3(LABEL_X, tableTop(sm.current).y + LABEL_BASE_ABOVE_TABLE + row * LABEL_ROW_STEP, Math.max(pt[2], LABEL_MIN_Z))
    const from = new Vector3(...pt)
    const dir = anchor.clone().sub(from)
    dot.current.position.copy(from)
    leader.current.position.copy(from).addScaledVector(dir, 0.5)
    leader.current.quaternion.copy(new Quaternion().setFromUnitVectors(Y_AXIS, dir.clone().normalize()))
    leader.current.scale.set(1, dir.length(), 1)
    label.current.position.copy(anchor)
  })
  return (
    <group ref={root} visible={false}>
      <mesh ref={dot} scale={DOT_RADIUS}>
        <sphereGeometry args={[1, 12, 8]} />
        <meshStandardMaterial color="#ff8a1f" emissive="#ff6a00" emissiveIntensity={0.8} />
      </mesh>
      <mesh ref={leader} scale={[1, 1, 1]}>
        <cylinderGeometry args={[LEADER_RADIUS, LEADER_RADIUS, 1, 5]} />
        <meshBasicMaterial color="#ffb066" />
      </mesh>
      <sprite ref={label} scale={[LABEL_HEIGHT * aspect, LABEL_HEIGHT, 1]} center={[1, 0.5]} renderOrder={10}>
        <spriteMaterial map={map} sizeAttenuation={false} toneMapped={false} />
      </sprite>
    </group>
  )
}

export function SurfaceMarks({ sm, posed, marks, statureMm }: { sm: Live<Snapshot>; posed: Live<Posed | null>; marks: SurfaceMark[]; statureMm: number }) {
  return (
    <>
      {marks.map((m, i) => (
        <Mark key={m.name} mark={m} row={i} sm={sm} posed={posed} statureMm={statureMm} />
      ))}
    </>
  )
}

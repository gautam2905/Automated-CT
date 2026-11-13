import { useFrame } from '@react-three/fiber'
import { memo, useEffect, useMemo, useRef } from 'react'
import { Group, Matrix4, MeshStandardMaterial, Quaternion, Vector3 } from 'three'
import type { Rig } from './figureRig'
import type { Vec3 } from './layout'
import { cross, sub, unit } from './vec'
import type { Live } from './useSmoothed'

export const FIGURE_COLOURS = {
  skin: '#d6a584',
  hair: '#3a2c26',
  gown: '#a9cfd0',
  pants: '#8db6c9',
  scrubs: '#2f7f8c',
  scrubsDark: '#256772',
  shoes: '#f1f3f5',
  techHair: '#5a4034',
} as const
export type MatKey = keyof typeof FIGURE_COLOURS

/** A figure's pose for one frame: joints plus the body axes (side, up, front) and the breath. */
export interface Posed {
  rig: Rig
  axes: [Vec3, Vec3, Vec3]
  breath: number
  /** 0..1 how far the figure has lain down (labels show only when lying). */
  lie: number
}

export function makePosed(rig: Rig, breath: number, lie: number): Posed {
  const up = unit(sub(rig.neck, rig.pelvis))
  const side = unit(sub(rig.shoulderL, rig.shoulderR))
  return { rig, axes: [side, up, cross(side, up)], breath, lie }
}

export type PartSpec =
  | { kind: 'limb'; a: (p: Posed) => Vec3; b: (p: Posed) => Vec3; r0: number; r1: number; mat: MatKey }
  | { kind: 'ellipsoid'; centre: (p: Posed) => Vec3; radii: (p: Posed) => Vec3; mat: MatKey }

const Y_AXIS = new Vector3(0, 1, 0)
const tmpDir = new Vector3()
const tmpQuat = new Quaternion()
const tmpMat = new Matrix4()
const tmpX = new Vector3()
const tmpY = new Vector3()
const tmpZ = new Vector3()

function applyLimb(g: Group, part: Extract<PartSpec, { kind: 'limb' }>, p: Posed) {
  const a = part.a(p)
  const b = part.b(p)
  tmpDir.set(b[0] - a[0], b[1] - a[1], b[2] - a[2])
  const len = Math.max(tmpDir.length(), 1e-4)
  const [cyl, sa, sb] = g.children
  cyl.position.set((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
  cyl.quaternion.copy(tmpQuat.setFromUnitVectors(Y_AXIS, tmpDir.normalize()))
  cyl.scale.set(1, len, 1)
  sa.position.set(a[0], a[1], a[2])
  sa.scale.setScalar(part.r0)
  sb.position.set(b[0], b[1], b[2])
  sb.scale.setScalar(part.r1)
}

function applyEllipsoid(g: Group, part: Extract<PartSpec, { kind: 'ellipsoid' }>, p: Posed) {
  const c = part.centre(p)
  const r = part.radii(p)
  const m = g.children[0]
  tmpMat.makeBasis(tmpX.set(...p.axes[0]), tmpY.set(...p.axes[1]), tmpZ.set(...p.axes[2]))
  m.quaternion.setFromRotationMatrix(tmpMat)
  m.position.set(c[0], c[1], c[2])
  m.scale.set(r[0], r[1], r[2])
}

interface FigureProps {
  parts: PartSpec[]
  /** Set each frame by the caller; null hides the figure. */
  posed: Live<Posed | null>
}

/**
 * A figure of limbs and ellipsoids built once per `parts`. Each frame the meshes are moved in place
 * from `posed`; React is not involved in the motion.
 */
function FigureImpl({ parts, posed }: FigureProps) {
  const materials = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(FIGURE_COLOURS).map(([k, colour]) => [k, new MeshStandardMaterial({ color: colour, roughness: k === 'skin' ? 0.6 : 0.8 })]),
      ) as Record<MatKey, MeshStandardMaterial>,
    [],
  )
  useEffect(() => () => Object.values(materials).forEach((m) => m.dispose()), [materials])
  const root = useRef<Group>(null)
  const groups = useRef<(Group | null)[]>([])
  useFrame(() => {
    const p = posed.current
    if (root.current) root.current.visible = p !== null
    if (!p) return
    parts.forEach((part, i) => {
      const g = groups.current[i]
      if (!g) return
      if (part.kind === 'limb') applyLimb(g, part, p)
      else applyEllipsoid(g, part, p)
    })
  })
  return (
    <group ref={root} visible={false}>
      {parts.map((part, i) => (
        <group key={i} ref={(el) => void (groups.current[i] = el)}>
          {part.kind === 'limb' ? (
            <>
              <mesh material={materials[part.mat]} castShadow>
                <cylinderGeometry args={[part.r1, part.r0, 1, 18]} />
              </mesh>
              <mesh material={materials[part.mat]} castShadow>
                <sphereGeometry args={[1, 18, 12]} />
              </mesh>
              <mesh material={materials[part.mat]} castShadow>
                <sphereGeometry args={[1, 18, 12]} />
              </mesh>
            </>
          ) : (
            <mesh material={materials[part.mat]} castShadow>
              <sphereGeometry args={[1, 24, 16]} />
            </mesh>
          )}
        </group>
      ))}
    </group>
  )
}

export const Figure = memo(FigureImpl)

export const limb = (a: (p: Posed) => Vec3, b: (p: Posed) => Vec3, r0: number, r1: number, mat: MatKey): PartSpec => ({ kind: 'limb', a, b, r0, r1, mat })
export const ellipsoid = (centre: (p: Posed) => Vec3, radii: (p: Posed) => Vec3, mat: MatKey): PartSpec => ({ kind: 'ellipsoid', centre, radii, mat })

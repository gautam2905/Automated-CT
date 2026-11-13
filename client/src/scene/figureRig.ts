import type { Snapshot } from '../api/types.gen'
import { PERSON_SPOTS, TABLE_GEOMETRY, type Vec3 } from './layout'
import { bodyRoomZ, tableTop, tableZ } from './transforms'
import { cross, sub, unit } from './vec'

const MM = 0.001
const REFERENCE_STATURE_M = 1.72

export const JOINTS = [
  'head', 'neck', 'chest', 'chestFront', 'pelvis',
  'shoulderL', 'shoulderR', 'elbowL', 'elbowR', 'wristL', 'wristR',
  'hipL', 'hipR', 'kneeL', 'kneeR', 'ankleL', 'ankleR', 'toeL', 'toeR',
] as const
export type JointName = (typeof JOINTS)[number]
export type Rig = Record<JointName, Vec3>

/** Body landmarks as a fraction of stature, measured from the top of the head downward. */
export const ZB = { head: 0.065, neck: 0.14, shoulder: 0.185, chest: 0.28, hip: 0.5, knee: 0.715, ankle: 0.955, toe: 0.975 }

/** Frame a body is placed in: where the vertex is and which way its head, front and left point. */
interface Frame { vertex: Vec3; up: Vec3; front: Vec3; left: Vec3 }

function frameFrom(vertex: Vec3, up: Vec3, front: Vec3): Frame {
  return { vertex, up, front, left: cross(up, front) }
}

/** Point of the body at (`zb` m below the vertex, `lat` m to the patient's left, `out` m out of the front). */
function place(f: Frame, zb: number, lat: number, out: number): Vec3 {
  return [
    f.vertex[0] - f.up[0] * zb + f.left[0] * lat + f.front[0] * out,
    f.vertex[1] - f.up[1] * zb + f.left[1] * lat + f.front[1] * out,
    f.vertex[2] - f.up[2] * zb + f.left[2] * lat + f.front[2] * out,
  ]
}

interface RigOptions { armsUp: boolean; armOut: number }

function templateRig(f: Frame, stature: number, o: RigOptions): Rig {
  const k = stature / REFERENCE_STATURE_M
  const z = (frac: number) => frac * stature
  const side = (lat: number): [number, number] => [lat * k, -lat * k]
  const elbowZ = o.armsUp ? 0 : z(0.37)
  const wristZ = o.armsUp ? -z(0.16) : z(0.53)
  const elbowLat = o.armsUp ? 0.24 : 0.215
  const wristLat = o.armsUp ? 0.15 : 0.21
  const armOut = o.armsUp ? o.armOut : 0
  const pair = (zb: number, lat: number, out: number): [Vec3, Vec3] => {
    const [l, r] = side(lat)
    return [place(f, zb, l, out), place(f, zb, r, out)]
  }
  const [shoulderL, shoulderR] = pair(z(ZB.shoulder), 0.19, 0)
  const [elbowL, elbowR] = pair(elbowZ, elbowLat, armOut)
  const [wristL, wristR] = pair(wristZ, wristLat, armOut)
  const [hipL, hipR] = pair(z(ZB.hip), 0.09, 0)
  const [kneeL, kneeR] = pair(z(ZB.knee), 0.095, 0)
  const [ankleL, ankleR] = pair(z(ZB.ankle), 0.09, 0)
  const [toeL, toeR] = pair(z(ZB.toe), 0.09, 0.11 * k)
  return {
    head: place(f, z(ZB.head), 0, 0), neck: place(f, z(ZB.neck), 0, 0),
    chest: place(f, z(ZB.chest), 0, 0), chestFront: place(f, z(ZB.chest), 0, 0.11 * k),
    pelvis: place(f, z(0.52), 0, 0),
    shoulderL, shoulderR, elbowL, elbowR, wristL, wristR,
    hipL, hipR, kneeL, kneeR, ankleL, ankleR, toeL, toeR,
  }
}

function rotateAboutY(p: Vec3, centre: Vec3, rad: number): Vec3 {
  const dx = p[0] - centre[0]
  const dz = p[2] - centre[2]
  const c = Math.cos(rad)
  const sn = Math.sin(rad)
  return [centre[0] + dx * c + dz * sn, p[1], centre[2] - dx * sn + dz * c]
}

export function mapRig(rig: Rig, fn: (p: Vec3) => Vec3): Rig {
  const out = {} as Rig
  for (const j of JOINTS) out[j] = fn(rig[j])
  return out
}

export function lerpRig(a: Rig, b: Rig, t: number): Rig {
  const out = {} as Rig
  for (const j of JOINTS) {
    out[j] = [a[j][0] + (b[j][0] - a[j][0]) * t, a[j][1] + (b[j][1] - a[j][1]) * t, a[j][2] + (b[j][2] - a[j][2]) * t]
  }
  return out
}

const bodyDepth = (stature: number) => 0.115 * (stature / REFERENCE_STATURE_M)

/**
 * The figure lying on the tabletop, from the pose and table in the snapshot.
 * Signs: `lateral_offset_mm` is +x in room space (metres = mm / 1000). `yaw_deg` turns the body about the
 * vertical through its midpoint in the three.js sense (positive turns +z toward +x). The patient's left is
 * -x for supine feet first (head at +z, face up); it flips for prone and for head first.
 */
export function lyingRig(s: Snapshot): Rig {
  const p = s.pose
  const stature = p.stature_mm * MM
  const headPlusZ = p.entry === 'feet_first'
  const up: Vec3 = [0, 0, headPlusZ ? 1 : -1]
  const front: Vec3 = [0, p.orientation === 'supine' ? 1 : -1, 0]
  const surfaceY = tableTop(s).y + TABLE_GEOMETRY.mattressThickness
  const vertex: Vec3 = [p.lateral_offset_mm * MM, surfaceY + bodyDepth(stature), bodyRoomZ(s, 0)]
  // Arms-up arms rest on the mattress: move them from the body axis toward the table, which is
  // against `front` when supine and along `front` when prone.
  const towardTable = p.orientation === 'supine' ? -1 : 1
  const armOut = towardTable * bodyDepth(stature) * 0.75
  const rig = templateRig(frameFrom(vertex, up, front), stature, { armsUp: p.arms === 'up', armOut })
  const centre: Vec3 = [vertex[0], 0, bodyRoomZ(s, p.stature_mm / 2)]
  return mapRig(rig, (pt) => rotateAboutY(pt, centre, (p.yaw_deg * Math.PI) / 180))
}

/** Standing at `pos` (feet), facing yaw `yawRad` (0 faces +z). */
export function standingRig(stature: number, pos: Vec3, yawRad: number): Rig {
  const front: Vec3 = [Math.sin(yawRad), 0, Math.cos(yawRad)]
  const f = frameFrom([pos[0], pos[1] + stature, pos[2]], [0, 1, 0], front)
  return templateRig(f, stature, { armsUp: false, armOut: 0 })
}

/** Sitting on the table edge, legs hanging off the -x side. */
export function sittingRig(s: Snapshot): Rig {
  const stature = s.pose.stature_mm * MM
  const k = stature / REFERENCE_STATURE_M
  const hipY = tableTop(s).y + TABLE_GEOMETRY.mattressThickness + 0.1 * k
  const hip: Vec3 = [PERSON_SPOTS.sitHipX, hipY, tableZ(s, PERSON_SPOTS.sitAlongTabletopMm)]
  const front: Vec3 = [-1, 0, 0]
  const vertex: Vec3 = [hip[0], hip[1] + ZB.hip * stature, hip[2]]
  const rig = templateRig(frameFrom(vertex, [0, 1, 0], front), stature, { armsUp: false, armOut: 0 })
  const thigh = (ZB.knee - ZB.hip) * stature
  const shin = (ZB.ankle - ZB.knee) * stature
  for (const sd of ['L', 'R'] as const) {
    const hp = rig[`hip${sd}`]
    const kn: Vec3 = [hp[0] - thigh, hp[1] - 0.02, hp[2]]
    const an: Vec3 = [kn[0] - 0.03, kn[1] - shin, kn[2]]
    rig[`knee${sd}`] = kn
    rig[`ankle${sd}`] = an
    rig[`toe${sd}`] = [an[0] - 0.11 * k, an[1] - 0.03, an[2]]
  }
  return rig
}

/** Unit vector out of the front of the torso. */
export function torsoFront(rig: Rig): Vec3 {
  return unit(cross(sub(rig.shoulderL, rig.shoulderR), sub(rig.neck, rig.pelvis)))
}

/** A point on the front surface of the body at `zBodyMm` below the vertex. */
export function surfacePoint(rig: Rig, zBodyMm: number, stature: number): Vec3 {
  const frac = (zBodyMm * MM) / stature
  const mid = (a: Vec3, b: Vec3): Vec3 => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2]
  const stops: [number, Vec3][] = [
    [ZB.head, rig.head],
    [ZB.neck, rig.neck],
    [ZB.hip, mid(rig.hipL, rig.hipR)],
    [ZB.knee, mid(rig.kneeL, rig.kneeR)],
    [ZB.ankle, mid(rig.ankleL, rig.ankleR)],
  ]
  let i = 0
  while (i < stops.length - 2 && frac > stops[i + 1][0]) i++
  const [f0, p0] = stops[i]
  const [f1, p1] = stops[i + 1]
  const t = Math.min(1.5, Math.max(-0.5, (frac - f0) / (f1 - f0)))
  const spine: Vec3 = [p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t, p0[2] + (p1[2] - p0[2]) * t]
  const out = torsoFront(rig)
  const depth = (frac < ZB.hip ? 0.1 : 0.07) * (stature / REFERENCE_STATURE_M)
  return [spine[0] + out[0] * depth, spine[1] + out[1] * depth, spine[2] + out[2] * depth]
}

/** Where the walk blend should head. On leaving, the patient first gets up (lying and sitting blends reach zero) and only then walks. */
export function walkGoal(stage: string, lie: number, sit: number): number {
  if (stage === 'leaving') return lie + sit > UPRIGHT_BLEND ? 1 : 0
  return stage === 'away' ? 0 : 1
}

const UPRIGHT_BLEND = 0.05

import type { Snapshot } from '../api/types.gen'

export const MAX_STEP_S = 0.1
const SETTLE_EPS = 1e-4

/** Exponential ease of `current` toward `target`; `rate` is 1/s, larger is quicker. */
export function easeToward(current: number, target: number, rate: number, dtS: number): number {
  if (rate <= 0) return target
  const next = target + (current - target) * Math.exp(-rate * Math.min(dtS, MAX_STEP_S))
  return Math.abs(next - target) < SETTLE_EPS * Math.max(1, Math.abs(target)) ? target : next
}

/** Shortest signed difference between two angles, radians. */
export function angleDelta(from: number, to: number): number {
  const twoPi = Math.PI * 2
  return ((((to - from + Math.PI) % twoPi) + twoPi) % twoPi) - Math.PI
}

/** The continuously moving values of a snapshot, as currently displayed. */
export interface EasedValues {
  height: number
  long: number
  lateral: number
  yaw: number
  breath: number
  tubeDeg: number
}

const TABLE_RATE = 8
const POSE_RATE = 10
const TUBE_RATE = 30

export function easedFrom(s: Snapshot): EasedValues {
  return {
    height: s.table.height_mm,
    long: s.table.long_mm,
    lateral: s.pose.lateral_offset_mm,
    yaw: s.pose.yaw_deg,
    breath: s.pose.breath,
    tubeDeg: s.scanner.tube_angle_deg,
  }
}

export function stepEased(v: EasedValues, t: Snapshot, dt: number): EasedValues {
  const tubeDiff = (angleDelta((v.tubeDeg * Math.PI) / 180, (t.scanner.tube_angle_deg * Math.PI) / 180) * 180) / Math.PI
  return {
    height: easeToward(v.height, t.table.height_mm, TABLE_RATE, dt),
    long: easeToward(v.long, t.table.long_mm, TABLE_RATE, dt),
    lateral: easeToward(v.lateral, t.pose.lateral_offset_mm, POSE_RATE, dt),
    yaw: easeToward(v.yaw, t.pose.yaw_deg, POSE_RATE, dt),
    breath: easeToward(v.breath, t.pose.breath, POSE_RATE, dt),
    tubeDeg: v.tubeDeg + tubeDiff * (1 - Math.exp(-TUBE_RATE * Math.min(dt, MAX_STEP_S))),
  }
}

export function withEased(t: Snapshot, v: EasedValues): Snapshot {
  return {
    ...t,
    table: { ...t.table, height_mm: v.height, long_mm: v.long },
    pose: { ...t.pose, lateral_offset_mm: v.lateral, yaw_deg: v.yaw, breath: v.breath },
    scanner: { ...t.scanner, tube_angle_deg: v.tubeDeg },
  }
}

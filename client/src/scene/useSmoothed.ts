import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import type { Snapshot } from '../api/types.gen'
import { easeToward, easedFrom, stepEased, withEased, type EasedValues } from './smoothMath'

export { angleDelta, easeToward } from './smoothMath'

/** A value read by frame callbacks; nothing here ever sets React state. */
export interface Live<T> {
  current: T
}

// Frame callback order: easing first, then figure posing, then everything that draws (priority 0).
// Negative priorities do not take over R3F's render loop.
export const EASE_PRIORITY = -2
export const POSE_PRIORITY = -1

/** A value that eases toward `target` (a number, or a function read every frame) every frame, held in a ref. Read `.current` in a frame callback. */
export function useEasedRef(target: number | (() => number), ratePerS: number): Live<number> {
  const read = (t: number | (() => number)): number => (typeof t === 'function' ? t() : t)
  const value = useRef(read(target))
  const goal = useRef(target)
  goal.current = target
  useFrame((_, dt) => {
    const to = read(goal.current)
    if (value.current !== to) value.current = easeToward(value.current, to, ratePerS, dt)
  }, EASE_PRIORITY)
  return value
}

/**
 * The latest snapshot with every moving value eased, so 20 snapshots/s look continuous.
 * Updated in a frame callback; read `.current` from other frame callbacks. Causes no re-render.
 */
export function useSmoothedSnapshotRef(target: Live<Snapshot>): Live<Snapshot> {
  const values = useRef<EasedValues>(easedFrom(target.current))
  const shown = useRef<Snapshot>(target.current)
  useFrame((_, dt) => {
    values.current = stepEased(values.current, target.current, dt)
    shown.current = withEased(target.current, values.current)
  }, EASE_PRIORITY)
  return shown
}

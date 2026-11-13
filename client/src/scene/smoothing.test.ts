import { describe, expect, test } from 'vitest'
import type { Snapshot } from '../api/types.gen'
import sampleJson from '../test/sampleSnapshot.json'
import { angleDelta, easeToward, easedFrom, stepEased } from './smoothMath'

const sample = sampleJson as unknown as Snapshot

describe('smoothing maths', () => {
  test('easeToward approaches the target and settles exactly on it', () => {
    let v = 0
    for (let i = 0; i < 200; i++) v = easeToward(v, 10, 8, 1 / 60)
    expect(v).toBe(10)
    expect(easeToward(0, 10, 8, 1 / 60)).toBeGreaterThan(0)
    expect(easeToward(0, 10, 8, 1 / 60)).toBeLessThan(10)
  })

  test('the tube angle takes the short way across the 360 degree wrap', () => {
    const t = { ...sample, scanner: { ...sample.scanner, tube_angle_deg: 5 } }
    const v = { ...easedFrom(t), tubeDeg: 355 }
    expect(angleDelta((355 * Math.PI) / 180, (5 * Math.PI) / 180)).toBeCloseTo((10 * Math.PI) / 180)
    expect(stepEased(v, t, 1 / 60).tubeDeg).toBeGreaterThan(355)
  })
})

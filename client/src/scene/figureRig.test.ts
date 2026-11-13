import { describe, expect, it, test } from 'vitest'
import type { Snapshot } from '../api/types.gen'
import sampleJson from '../test/sampleSnapshot.json'
import { TABLE_GEOMETRY } from './layout'
import { lyingRig, walkGoal } from './figureRig'
import { tableTop } from './transforms'

const sample = sampleJson as unknown as Snapshot
const withPose = (p: Partial<Snapshot['pose']>): Snapshot => ({ ...sample, pose: { ...sample.pose, ...p } })

describe('lying rig', () => {
  test('feet first: the ankles are nearer the gantry than the head', () => {
    const rig = lyingRig(withPose({ entry: 'feet_first' }))
    expect(rig.ankleL[2]).toBeLessThan(rig.head[2])
  })

  test('arms up put the wrists beyond the head, arms down put them beside the hips', () => {
    const up = lyingRig(withPose({ arms: 'up', entry: 'feet_first' }))
    const down = lyingRig(withPose({ arms: 'down', entry: 'feet_first' }))
    expect(up.wristL[2]).toBeGreaterThan(up.head[2])
    expect(down.wristL[2]).toBeLessThan(down.head[2])
  })

  test('supine lies on the back: the chest is above the spine line, prone the reverse', () => {
    expect(lyingRig(withPose({ orientation: 'supine' })).chestFront[1]).toBeGreaterThan(
      lyingRig(withPose({ orientation: 'supine' })).pelvis[1],
    )
    expect(lyingRig(withPose({ orientation: 'prone' })).chestFront[1]).toBeLessThan(
      lyingRig(withPose({ orientation: 'prone' })).pelvis[1],
    )
  })
})

describe('lying rig on the table', () => {
  const surface = tableTop(sample).y + TABLE_GEOMETRY.mattressThickness

  test.each(['supine', 'prone'] as const)('arms up rest near the mattress when %s', (orientation) => {
    const rig = lyingRig(withPose({ arms: 'up', orientation }))
    for (const wrist of [rig.wristL, rig.wristR]) {
      expect(wrist[1]).toBeGreaterThan(surface)
      expect(wrist[1]).toBeLessThan(surface + 0.08)
    }
  })

  test('the patient left is -x for supine feet first, and flips for prone or head first', () => {
    const left = (p: Partial<Snapshot['pose']>) => {
      const rig = lyingRig(withPose({ yaw_deg: 0, lateral_offset_mm: 0, ...p }))
      return Math.sign(rig.shoulderL[0] - rig.shoulderR[0])
    }
    expect(left({ entry: 'feet_first', orientation: 'supine' })).toBe(-1)
    expect(left({ entry: 'feet_first', orientation: 'prone' })).toBe(1)
    expect(left({ entry: 'head_first', orientation: 'supine' })).toBe(1)
  })

  test('lateral offset moves the body to +x and a 90 degree yaw turns the head toward +x', () => {
    const base = lyingRig(withPose({ lateral_offset_mm: 0, yaw_deg: 0, entry: 'feet_first' }))
    const moved = lyingRig(withPose({ lateral_offset_mm: 50, yaw_deg: 0, entry: 'feet_first' }))
    expect(moved.head[0] - base.head[0]).toBeCloseTo(0.05)
    const turned = lyingRig(withPose({ lateral_offset_mm: 0, yaw_deg: 90, entry: 'feet_first' }))
    expect(turned.head[0]).toBeGreaterThan(0.5)
  })
})

describe('walkGoal', () => {
  it('keeps a leaving patient at the table until the patient is up', () => {
    expect(walkGoal('leaving', 0.6, 0)).toBe(1)
    expect(walkGoal('leaving', 0, 0.4)).toBe(1)
    expect(walkGoal('leaving', 0.01, 0.01)).toBe(0)
  })
  it('is one while the patient is in the room and zero when away', () => {
    expect(walkGoal('lying', 1, 0)).toBe(1)
    expect(walkGoal('entering', 0, 0)).toBe(1)
    expect(walkGoal('away', 0, 0)).toBe(0)
  })
})

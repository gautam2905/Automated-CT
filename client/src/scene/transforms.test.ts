import { describe, expect, test } from 'vitest'
import type { Snapshot } from '../api/types.gen'
import sampleJson from '../test/sampleSnapshot.json'
import { bodyRoomZ, patientRoot, tableTop, technologistSpot, tubeAngleRad } from './transforms'

const sample = sampleJson as unknown as Snapshot

const withTable = (s: Snapshot, t: Partial<Snapshot['table']>): Snapshot => ({ ...s, table: { ...s.table, ...t } })
const withPose = (s: Snapshot, p: Partial<Snapshot['pose']>): Snapshot => ({ ...s, pose: { ...s.pose, ...p } })
const withRoom = (s: Snapshot, r: Partial<Snapshot['room']>): Snapshot => ({ ...s, room: { ...s.room, ...r } })

describe('scene transforms', () => {
  test('the tabletop moves toward the gantry as travel increases', () => {
    const a = tableTop(withTable(sample, { long_mm: 0, height_mm: 890 }))
    const b = tableTop(withTable(sample, { long_mm: 1000, height_mm: 890 }))
    expect(a.y).toBeCloseTo(0.89)
    expect(a.zFront - b.zFront).toBeCloseTo(1.0)
  })

  test('feet first: the feet are nearer the gantry than the head', () => {
    const s = withPose(sample, { entry: 'feet_first', anchor_t_mm: 120, stature_mm: 1720 })
    expect(bodyRoomZ(s, 1720)).toBeLessThan(bodyRoomZ(s, 0))
    expect(patientRoot(s).headTowardPlusZ).toBe(true)
  })

  test('head first: the head is nearer the gantry than the feet', () => {
    const s = withPose(sample, { entry: 'head_first', anchor_t_mm: 120, stature_mm: 1720 })
    expect(bodyRoomZ(s, 0)).toBeLessThan(bodyRoomZ(s, 1720))
    expect(patientRoot(s).headTowardPlusZ).toBe(false)
  })

  test('a body point set at zero travel lands where the convention says', () => {
    const s = withTable(withPose(sample, { entry: 'feet_first', anchor_t_mm: 120, stature_mm: 1720 }), { long_mm: 0 })
    expect(bodyRoomZ(s, 1720)).toBeCloseTo((sample.scanner.front_clearance_mm + 120) / 1000)
  })

  test('patient root carries the lateral offset and yaw', () => {
    const s = withPose(sample, { lateral_offset_mm: 25, yaw_deg: 90 })
    expect(patientRoot(s).position[0]).toBeCloseTo(0.025)
    expect(patientRoot(s).yawRad).toBeCloseTo(Math.PI / 2)
  })

  test('the technologist stands at the console when the snapshot says so', () => {
    expect(technologistSpot(withRoom(sample, { technologist_at: 'console' }))).not.toEqual(
      technologistSpot(withRoom(sample, { technologist_at: 'gantry' })),
    )
  })

  test('the tube angle is returned in radians', () => {
    expect(tubeAngleRad({ ...sample, scanner: { ...sample.scanner, tube_angle_deg: 180 } })).toBeCloseTo(Math.PI)
  })
})

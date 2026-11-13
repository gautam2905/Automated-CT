import type { Snapshot } from '../api/types.gen'
import { PERSON_SPOTS, type Vec3 } from './layout'

const MM = 0.001

/** Tabletop surface height and the z of its gantry-side end, metres. */
export function tableTop(s: Snapshot): { y: number; zFront: number } {
  return {
    y: s.table.height_mm * MM,
    zFront: (s.scanner.front_clearance_mm - s.table.long_mm) * MM,
  }
}

/** Room z (m) of the tabletop point `tMm` from the gantry-side end of the tabletop. */
export function tableZ(s: Snapshot, tMm: number): number {
  return tableTop(s).zFront + tMm * MM
}

/** Room z (m) of the body point `zBodyMm` below the vertex, for a patient lying on the table. */
export function bodyRoomZ(s: Snapshot, zBodyMm: number): number {
  const p = s.pose
  const t = p.entry === 'feet_first' ? p.anchor_t_mm + (p.stature_mm - zBodyMm) : p.anchor_t_mm + zBodyMm
  return tableZ(s, t)
}

export interface PatientRoot {
  /** Midpoint of the lying body on the tabletop surface. */
  position: Vec3
  yawRad: number
  headTowardPlusZ: boolean
}

export function patientRoot(s: Snapshot): PatientRoot {
  return {
    position: [s.pose.lateral_offset_mm * MM, tableTop(s).y, bodyRoomZ(s, s.pose.stature_mm / 2)],
    yawRad: (s.pose.yaw_deg * Math.PI) / 180,
    headTowardPlusZ: s.pose.entry === 'feet_first',
  }
}

export function technologistSpot(s: Snapshot): Vec3 {
  switch (s.room.technologist_at) {
    case 'reception':
      return PERSON_SPOTS.techReception
    case 'preparation':
      return PERSON_SPOTS.techPreparation
    case 'gantry':
      return PERSON_SPOTS.techGantry
    case 'console':
      return PERSON_SPOTS.techConsole
  }
}

/** Yaw (about +y, 0 = facing +z) the technologist faces at each spot. */
export function technologistFacing(s: Snapshot): number {
  switch (s.room.technologist_at) {
    case 'reception':
      return Math.PI / 2 // toward the door and the room (+x)
    case 'preparation':
      return 2.75 // toward the table and the patient standing beside it
    case 'gantry':
      return -Math.PI / 2 - 0.35 // toward the table and patient
    case 'console':
      return -Math.PI / 2 // toward the window (-x)
  }
}

export function tubeAngleRad(s: Snapshot): number {
  return (s.scanner.tube_angle_deg * Math.PI) / 180
}

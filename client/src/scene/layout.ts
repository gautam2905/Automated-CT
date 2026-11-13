// Fixed room layout in metres. y up, scan plane at z = 0, table on the +z side.
// Scanner and table dimensions are NOT here: they come from the snapshot.

export type Vec3 = [number, number, number]

export const ROOM = {
  xMin: -2.8,
  xMax: 2.8,
  zMin: -2.0,
  zMax: 4.4,
  height: 2.9,
  wallThickness: 0.2,
} as const

/** Door in the left wall (x = xMin), swinging into the room. */
export const DOOR = { zCentre: 1.8, width: 1.0, height: 2.1 } as const

/** Lead-glass window in the right wall (x = xMax), into the control room. */
export const WINDOW = { zMin: -1.4, zMax: 0.5, yMin: 0.95, yMax: 2.0 } as const

/** Control room: the alcove behind the window. */
export const CONTROL_ROOM = { xMax: 5.6, zMax: 1.0 } as const

export const DESK = { x: 3.45, z: -0.45, length: 1.7, depth: 0.7, height: 0.74 } as const

export const GANTRY = { halfDepth: 0.55, width: 2.3, height: 1.95 } as const

export const TABLE_GEOMETRY = {
  width: 0.46,
  thickness: 0.05,
  length: 2.0,
  mattressThickness: 0.03,
  columnZ: 1.7,
} as const

export const PERSON_SPOTS = {
  /** Where the patient stands beside the table. */
  patientStand: [-0.85, 0, 1.3] as Vec3,
  /** Outside the door; the patient walks in from here. */
  patientDoor: [-3.7, 0, 1.8] as Vec3,
  /** Patient sitting on the table edge: hip position on the tabletop (x only; z from table). */
  sitHipX: -0.04,
  sitAlongTabletopMm: 800,
  techReception: [-4.0, 0, 2.9] as Vec3,
  techPreparation: [-1.35, 0, 2.7] as Vec3,
  techGantry: [0.85, 0, 1.0] as Vec3,
  techConsole: [4.3, 0, -0.45] as Vec3,
  injector: [1.05, 0, 2.85] as Vec3,
}

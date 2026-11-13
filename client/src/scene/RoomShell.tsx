import { useFrame, useThree } from '@react-three/fiber'
import { memo, useEffect, useMemo, useRef, type RefObject } from 'react'
import type { Group, MeshStandardMaterial, PointLight } from 'three'
import ControlRoom from './ControlRoom'
import { CONTROL_ROOM, DOOR, ROOM, WINDOW } from './layout'
import { Box, COLOURS, Matte, WallAlongZ, drawCanvasTexture, useFloorTexture } from './shellParts'
import { useEasedRef } from './useSmoothed'

const DOOR_OPEN_RAD = 1.45
const T = ROOM.wallThickness
const LEFT_WALL_X = ROOM.xMin - T / 2
const RIGHT_WALL_X = ROOM.xMax + T / 2

function Floor() {
  const map = useFloorTexture()
  const w = CONTROL_ROOM.xMax + 0.15 - (ROOM.xMin - 2.4)
  const d = ROOM.zMax - ROOM.zMin
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[(CONTROL_ROOM.xMax + 0.15 + ROOM.xMin - 2.4) / 2, 0, (ROOM.zMax + ROOM.zMin) / 2]} receiveShadow>
      <planeGeometry args={[w, d]} />
      <meshStandardMaterial map={map} roughness={0.5} metalness={0} />
    </mesh>
  )
}

function Skirting() {
  const h = 0.1
  return (
    <>
      <Box position={[(ROOM.xMin + CONTROL_ROOM.xMax) / 2, h / 2, ROOM.zMin + 0.02]} size={[CONTROL_ROOM.xMax - ROOM.xMin, h, 0.04]} shadow={false}>
        <Matte colour={COLOURS.wallTrim} />
      </Box>
    </>
  )
}

function Door({ doorOpen }: { doorOpen: boolean }) {
  const openness = useEasedRef(doorOpen ? 1 : 0, 3)
  const leaf = useRef<Group>(null)
  useFrame(() => {
    if (leaf.current) leaf.current.rotation.y = -DOOR_OPEN_RAD * openness.current
  })
  const hingeZ = DOOR.zCentre + DOOR.width / 2
  const sign = useMemo(
    () =>
      drawCanvasTexture(128, 128, (g) => {
        g.fillStyle = '#f2c230'
        g.fillRect(0, 0, 128, 128)
        g.fillStyle = '#1b1b1b'
        for (let i = 0; i < 3; i++) {
          g.beginPath()
          const a0 = (i * 2 * Math.PI) / 3 - Math.PI / 6
          g.moveTo(64, 64)
          g.arc(64, 64, 46, a0, a0 + Math.PI / 3)
          g.closePath()
          g.fill()
        }
        g.beginPath()
        g.arc(64, 64, 9, 0, Math.PI * 2)
        g.fill()
      }),
    [],
  )
  useEffect(() => () => sign.dispose(), [sign])
  const frameY = DOOR.height / 2
  return (
    <group>
      <Box position={[LEFT_WALL_X, frameY, DOOR.zCentre - DOOR.width / 2 - 0.025]} size={[T + 0.04, DOOR.height, 0.05]}>
        <Matte colour={COLOURS.frame} rough={0.5} />
      </Box>
      <Box position={[LEFT_WALL_X, frameY, DOOR.zCentre + DOOR.width / 2 + 0.025]} size={[T + 0.04, DOOR.height, 0.05]}>
        <Matte colour={COLOURS.frame} rough={0.5} />
      </Box>
      <Box position={[LEFT_WALL_X, DOOR.height + 0.025, DOOR.zCentre]} size={[T + 0.04, 0.05, DOOR.width + 0.1]}>
        <Matte colour={COLOURS.frame} rough={0.5} />
      </Box>
      <group ref={leaf} position={[LEFT_WALL_X, 0, hingeZ]}>
        <Box position={[0, frameY - 0.01, -DOOR.width / 2]} size={[0.06, DOOR.height - 0.03, DOOR.width - 0.02]}>
          <meshStandardMaterial color="#6f8fa0" roughness={0.45} metalness={0.05} />
        </Box>
        <Box position={[0.035, 1.55, -DOOR.width / 2]} size={[0.01, 0.55, 0.22]} shadow={false}>
          <meshStandardMaterial color="#bcd9e0" roughness={0.1} transparent opacity={0.6} />
        </Box>
        <Box position={[0.05, 1.0, -DOOR.width + 0.12]} size={[0.05, 0.03, 0.16]}>
          <meshStandardMaterial color="#cfd5d9" metalness={0.8} roughness={0.25} />
        </Box>
        <mesh position={[0.036, 1.95, -DOOR.width / 2]} rotation={[0, Math.PI / 2, 0]}>
          <planeGeometry args={[0.2, 0.2]} />
          <meshBasicMaterial map={sign} />
        </mesh>
      </group>
    </group>
  )
}

function WarningLight({ on }: { on: boolean }) {
  const glow = useEasedRef(on ? 1 : 0, 12)
  const face = useRef<MeshStandardMaterial>(null)
  const light = useRef<PointLight>(null)
  useFrame(() => {
    const g = glow.current
    face.current?.color.setRGB((120 + 135 * g) / 255, (40 + 35 * g) / 255, (36 + 30 * g) / 255)
    if (face.current) face.current.emissiveIntensity = 2.2 * g
    if (light.current) light.current.intensity = 2.5 * g
  })
  const label = useMemo(
    () =>
      drawCanvasTexture(256, 96, (g) => {
        g.fillStyle = '#ffffff'
        g.fillRect(0, 0, 256, 96)
        g.fillStyle = '#7a1612'
        g.font = 'bold 54px sans-serif'
        g.textAlign = 'center'
        g.textBaseline = 'middle'
        g.fillText('X-RAY ON', 128, 50)
      }),
    [],
  )
  useEffect(() => () => label.dispose(), [label])
  const x = ROOM.xMin + 0.04
  return (
    <group position={[x, 2.4, DOOR.zCentre]}>
      <Box position={[-0.005, 0, 0]} size={[0.07, 0.2, 0.46]}>
        <Matte colour={COLOURS.dark} rough={0.5} />
      </Box>
      <mesh position={[0.035, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
        <planeGeometry args={[0.42, 0.16]} />
        <meshStandardMaterial ref={face} map={label} color="#781e1c" emissive="#ff2a1a" emissiveMap={label} emissiveIntensity={0} roughness={0.4} />
      </mesh>
      <pointLight ref={light} position={[0.3, -0.1, 0]} color="#ff3b2a" intensity={0} distance={2.5} decay={2} />
    </group>
  )
}

function Window() {
  const { zMin, zMax, yMin, yMax } = WINDOW
  const zc = (zMin + zMax) / 2
  const bar = 0.06
  return (
    <group>
      <mesh position={[RIGHT_WALL_X, (yMin + yMax) / 2, zc]}>
        <boxGeometry args={[0.04, yMax - yMin, zMax - zMin]} />
        <meshPhysicalMaterial color="#c9e3d4" transparent opacity={0.16} roughness={0.04} metalness={0} depthWrite={false} envMapIntensity={1.2} />
      </mesh>
      {[yMin - bar / 2, yMax + bar / 2].map((y) => (
        <Box key={y} position={[RIGHT_WALL_X, y, zc]} size={[T + 0.04, bar, zMax - zMin + 2 * bar]}>
          <Matte colour={COLOURS.frame} rough={0.5} />
        </Box>
      ))}
      {[zMin - bar / 2, zMax + bar / 2].map((z) => (
        <Box key={z} position={[RIGHT_WALL_X, (yMin + yMax) / 2, z]} size={[T + 0.04, yMax - yMin, bar]}>
          <Matte colour={COLOURS.frame} rough={0.5} />
        </Box>
      ))}
    </group>
  )
}

function Ceiling({ visibleRef }: { visibleRef: RefObject<Group | null> }) {
  const w = CONTROL_ROOM.xMax - ROOM.xMin
  const d = ROOM.zMax - ROOM.zMin
  const panels: [number, number][] = [-1.4, 0, 1.4].flatMap((x) => [-1, 1.2, 3.4].map((z): [number, number] => [x, z]))
  return (
    <group ref={visibleRef} position={[(ROOM.xMin + CONTROL_ROOM.xMax) / 2, ROOM.height, (ROOM.zMin + ROOM.zMax) / 2]}>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <planeGeometry args={[w, d]} />
        <meshBasicMaterial color="#d9dfe3" />
      </mesh>
      {panels.map(([x, z]) => (
        <mesh key={`${x}:${z}`} position={[x - (ROOM.xMin + CONTROL_ROOM.xMax) / 2, -0.005, z - (ROOM.zMin + ROOM.zMax) / 2]} rotation={[Math.PI / 2, 0, 0]}>
          <planeGeometry args={[1.0, 0.55]} />
          <meshBasicMaterial color="#fffdf5" toneMapped={false} />
        </mesh>
      ))}
    </group>
  )
}

/** Hide a wall while the orbit camera is outside it, so the view is never blocked. */
function useWallCulling(left: RefObject<Group | null>, right: RefObject<Group | null>, ceiling: RefObject<Group | null>) {
  const camera = useThree((s) => s.camera)
  useFrame(() => {
    const p = camera.position
    if (left.current) left.current.visible = p.x > ROOM.xMin - 0.2
    if (ceiling.current) ceiling.current.visible = p.y < ROOM.height - 0.1
    if (right.current) right.current.visible = !(p.x > ROOM.xMax + 0.2 && p.z > CONTROL_ROOM.zMax)
  })
}

function RoomShellImpl({ doorOpen, warning }: { doorOpen: boolean; warning: boolean }) {
  const left = useRef<Group>(null)
  const right = useRef<Group>(null)
  const ceiling = useRef<Group>(null)
  useWallCulling(left, right, ceiling)
  const doorSpan = { a: DOOR.zCentre - DOOR.width / 2 - 0.05, b: DOOR.zCentre + DOOR.width / 2 + 0.05 }
  return (
    <group>
      <Floor />
      <Skirting />
      <Box position={[(ROOM.xMin + CONTROL_ROOM.xMax) / 2, ROOM.height / 2, ROOM.zMin - T / 2]} size={[CONTROL_ROOM.xMax - ROOM.xMin + 0.3, ROOM.height, T]}>
        <Matte colour={COLOURS.wall} />
      </Box>
      <group ref={left}>
        <WallAlongZ x={LEFT_WALL_X} zMin={ROOM.zMin - T} zMax={ROOM.zMax} thickness={T} height={ROOM.height} opening={{ ...doorSpan, y0: 0, y1: DOOR.height + 0.05 }} />
        <Door doorOpen={doorOpen} />
        <WarningLight on={warning} />
      </group>
      <group ref={right}>
        <WallAlongZ x={RIGHT_WALL_X} zMin={ROOM.zMin - T} zMax={ROOM.zMax} thickness={T} height={ROOM.height} opening={{ a: WINDOW.zMin - 0.06, b: WINDOW.zMax + 0.06, y0: WINDOW.yMin - 0.06, y1: WINDOW.yMax + 0.06 }} />
        <Window />
      </group>
      <ControlRoom />
      <Ceiling visibleRef={ceiling} />
    </group>
  )
}

export default memo(RoomShellImpl)

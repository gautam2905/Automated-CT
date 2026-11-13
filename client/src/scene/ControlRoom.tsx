import { useEffect, useMemo } from 'react'
import { CONTROL_ROOM, DESK, ROOM } from './layout'
import { Box, COLOURS, Matte, drawCanvasTexture } from './shellParts'

function useScreenTexture(kind: 'slice' | 'planning') {
  const tex = useMemo(
    () =>
      drawCanvasTexture(256, 192, (g) => {
        g.fillStyle = '#05090c'
        g.fillRect(0, 0, 256, 192)
        if (kind === 'slice') {
          g.fillStyle = '#6b7279'
          g.beginPath()
          g.ellipse(128, 96, 78, 60, 0, 0, Math.PI * 2)
          g.fill()
          g.fillStyle = '#1b2125'
          g.beginPath()
          g.ellipse(98, 94, 22, 34, 0.1, 0, Math.PI * 2)
          g.ellipse(158, 94, 22, 34, -0.1, 0, Math.PI * 2)
          g.fill()
          g.fillStyle = '#c9ced2'
          g.beginPath()
          g.arc(128, 112, 9, 0, Math.PI * 2)
          g.fill()
        } else {
          g.fillStyle = '#17323e'
          g.fillRect(8, 8, 240, 20)
          g.fillStyle = '#2b6e80'
          for (let i = 0; i < 5; i++) g.fillRect(14 + i * 46, 40, 38, 120)
          g.fillStyle = '#9fd6e3'
          for (let i = 0; i < 5; i++) g.fillRect(18 + i * 46, 100 + (i % 3) * 14, 30, 4)
        }
      }),
    [kind],
  )
  useEffect(() => () => tex.dispose(), [tex])
  return tex
}

function Monitor({ z, kind }: { z: number; kind: 'slice' | 'planning' }) {
  const map = useScreenTexture(kind)
  const y = DESK.height + 0.27
  return (
    <group position={[DESK.x - 0.05, 0, z]} rotation={[0, Math.PI / 2 - 0.12 * Math.sign(DESK.z - z || 1), 0]}>
      <Box position={[0, DESK.height + 0.07, 0]} size={[0.2, 0.02, 0.14]}>
        <Matte colour={COLOURS.dark} rough={0.4} />
      </Box>
      <Box position={[0, DESK.height + 0.15, -0.02]} size={[0.04, 0.16, 0.03]}>
        <Matte colour={COLOURS.dark} rough={0.4} />
      </Box>
      <Box position={[0, y, 0]} size={[0.56, 0.35, 0.035]}>
        <Matte colour="#11181c" rough={0.35} />
      </Box>
      <mesh position={[0, y, 0.0185]}>
        <planeGeometry args={[0.52, 0.31]} />
        <meshStandardMaterial map={map} emissive="#ffffff" emissiveMap={map} emissiveIntensity={0.9} roughness={0.4} />
      </mesh>
    </group>
  )
}

/** The control room behind the window: partition, back wall, desk with two monitors. */
export default function ControlRoom() {
  const t = ROOM.wallThickness
  const wallLen = CONTROL_ROOM.xMax - ROOM.xMax
  return (
    <group>
      <Box position={[ROOM.xMax + t + wallLen / 2, ROOM.height / 2, CONTROL_ROOM.zMax + 0.075]} size={[wallLen, ROOM.height, 0.15]}>
        <Matte colour={COLOURS.wall} />
      </Box>
      <Box position={[CONTROL_ROOM.xMax + 0.075, ROOM.height / 2, (ROOM.zMin + CONTROL_ROOM.zMax) / 2]} size={[0.15, ROOM.height, CONTROL_ROOM.zMax - ROOM.zMin + 0.3]}>
        <Matte colour={COLOURS.wall} />
      </Box>
      <Box position={[DESK.x, DESK.height - 0.02, DESK.z]} size={[DESK.depth, 0.04, DESK.length]}>
        <meshStandardMaterial color="#d8dcde" roughness={0.35} />
      </Box>
      <Box position={[DESK.x + 0.1, (DESK.height - 0.04) / 2, DESK.z]} size={[DESK.depth - 0.2, DESK.height - 0.04, DESK.length - 0.1]}>
        <Matte colour="#4a5963" rough={0.6} />
      </Box>
      <Monitor z={DESK.z - 0.4} kind="slice" />
      <Monitor z={DESK.z + 0.4} kind="planning" />
      <Box position={[DESK.x + 0.2, DESK.height + 0.01, DESK.z]} size={[0.16, 0.02, 0.42]}>
        <Matte colour="#222b31" rough={0.5} />
      </Box>
    </group>
  )
}

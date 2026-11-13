import { useFrame } from '@react-three/fiber'
import { memo, useRef } from 'react'
import type { Group, Mesh } from 'three'
import type { Snapshot } from '../api/types.gen'
import { TABLE_GEOMETRY as G } from './layout'
import { Box, COLOURS, Matte } from './shellParts'
import { tableTop } from './transforms'
import { useSlotModel } from './useSlotModel'
import type { Live } from './useSmoothed'

const PLINTH_H = 0.18
const SLEEVE_TOP = 0.34
const CRADLE_H = 0.1

function Plastic({ colour = '#e3e7ea' }: { colour?: string }) {
  return <meshPhysicalMaterial color={colour} roughness={0.35} clearcoat={0.6} clearcoatRoughness={0.15} />
}

/**
 * Table base, telescoping column, cradle and the sliding tabletop with its mattress.
 * The moving parts are placed each frame from the eased snapshot; React never re-renders them.
 */
function TableImpl({ sm }: { sm: Live<Snapshot> }) {
  const slot = useSlotModel('table')
  const top = useRef<Group>(null)
  const cradle = useRef<Group>(null)
  const inner = useRef<Mesh>(null)
  useFrame(() => {
    const { y, zFront } = tableTop(sm.current)
    const cradleBottom = y - G.thickness - CRADLE_H
    const innerBottom = SLEEVE_TOP - 0.04
    const innerLen = Math.max(cradleBottom - innerBottom, 0.001)
    top.current?.position.set(0, y, zFront)
    cradle.current?.position.set(0, cradleBottom, G.columnZ)
    inner.current?.position.set(0, innerBottom + innerLen / 2, G.columnZ)
    inner.current?.scale.set(1, innerLen, 1)
  })
  if (slot) return <primitive object={slot} />
  return (
    <group>
      <Box position={[0, PLINTH_H / 2, G.columnZ]} size={[0.95, PLINTH_H, 1.05]}>
        <Plastic colour="#d3d9dd" />
      </Box>
      <Box position={[0, (PLINTH_H + SLEEVE_TOP) / 2, G.columnZ]} size={[0.5, SLEEVE_TOP - PLINTH_H, 0.5]}>
        <Plastic />
      </Box>
      <mesh ref={inner} castShadow receiveShadow>
        <boxGeometry args={[0.44, 1, 0.44]} />
        <meshStandardMaterial color="#aab4bb" roughness={0.4} metalness={0.5} />
      </mesh>
      <group ref={cradle}>
        <Box position={[0, CRADLE_H / 2, 0]} size={[0.56, CRADLE_H, 1.1]}>
          <Plastic />
        </Box>
      </group>
      <group ref={top}>
        <Box position={[0, -G.thickness / 2, G.length / 2]} size={[G.width, G.thickness, G.length]}>
          <Plastic colour="#f0f2f3" />
        </Box>
        <Box position={[0, G.mattressThickness / 2, 0.975]} size={[G.width - 0.03, G.mattressThickness, 1.85]}>
          <meshStandardMaterial color="#35566f" roughness={0.65} />
        </Box>
        <Box position={[0, -G.thickness - 0.006, G.length / 2]} size={[G.width - 0.1, 0.012, G.length - 0.04]} shadow={false}>
          <Matte colour={COLOURS.dark} />
        </Box>
      </group>
    </group>
  )
}

export default memo(TableImpl)

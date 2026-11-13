import { useMemo, type ReactNode } from 'react'
import { CanvasTexture, RepeatWrapping, SRGBColorSpace } from 'three'
import type { Vec3 } from './layout'

export const COLOURS = {
  wall: '#e6eaed',
  wallTrim: '#8f9fa8',
  floor: '#b9c3c9',
  frame: '#34434c',
  white: '#eceef0',
  steel: '#9aa5ad',
  dark: '#2a343b',
} as const

interface BoxProps {
  position: Vec3
  size: Vec3
  children: ReactNode
  rotationY?: number
  shadow?: boolean
}

/** A box with its centre at `position`. Pass a material as the child. */
export function Box({ position, size, children, rotationY = 0, shadow = true }: BoxProps) {
  return (
    <mesh position={position} rotation={[0, rotationY, 0]} castShadow={shadow} receiveShadow>
      <boxGeometry args={size} />
      {children}
    </mesh>
  )
}

export function Matte({ colour, rough = 0.85 }: { colour: string; rough?: number }) {
  return <meshStandardMaterial color={colour} roughness={rough} metalness={0} />
}

export function drawCanvasTexture(w: number, h: number, draw: (g: CanvasRenderingContext2D) => void): CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const g = canvas.getContext('2d')
  if (g) draw(g)
  const tex = new CanvasTexture(canvas)
  tex.colorSpace = SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

/** Vinyl floor tiles with fine grout lines. */
export function useFloorTexture(): CanvasTexture {
  return useMemo(() => {
    const tex = drawCanvasTexture(256, 256, (g) => {
      g.fillStyle = '#c3ccd1'
      g.fillRect(0, 0, 256, 256)
      g.fillStyle = '#bac4ca'
      g.fillRect(0, 0, 128, 128)
      g.fillRect(128, 128, 128, 128)
      g.fillStyle = '#9aa7af'
      g.fillRect(0, 0, 256, 2)
      g.fillRect(0, 0, 2, 256)
      g.fillRect(0, 127, 256, 2)
      g.fillRect(127, 0, 2, 256)
    })
    tex.wrapS = tex.wrapT = RepeatWrapping
    tex.repeat.set(12, 14)
    return tex
  }, [])
}

export interface Opening {
  /** Opening span along the wall, in wall coordinates (z), and in height. */
  a: number
  b: number
  y0: number
  y1: number
}

interface WallProps {
  /** Wall centre-plane x. The wall runs along z. */
  x: number
  zMin: number
  zMax: number
  thickness: number
  height: number
  opening?: Opening
}

/** A wall along z, optionally with a rectangular opening. Pieces are boxes around the hole. */
export function WallAlongZ({ x, zMin, zMax, thickness, height, opening }: WallProps) {
  const piece = (z0: number, z1: number, y0: number, y1: number, key: string) =>
    z1 - z0 > 1e-3 && y1 - y0 > 1e-3 ? (
      <Box key={key} position={[x, (y0 + y1) / 2, (z0 + z1) / 2]} size={[thickness, y1 - y0, z1 - z0]}>
        <Matte colour={COLOURS.wall} />
      </Box>
    ) : null
  if (!opening) return <>{piece(zMin, zMax, 0, height, 'full')}</>
  const { a, b, y0, y1 } = opening
  return (
    <>
      {piece(zMin, a, 0, height, 'near')}
      {piece(b, zMax, 0, height, 'far')}
      {piece(a, b, 0, y0, 'below')}
      {piece(a, b, y1, height, 'above')}
    </>
  )
}

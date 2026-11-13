import { OrbitControls } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import { MathUtils, Vector3 } from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import type { Vec3 } from './layout'

export type CameraPreset = 'room' | 'side' | 'top' | 'bore' | 'control'

interface PresetView { position: Vec3; target: Vec3; fov: number }

export const CAMERA_PRESETS: Record<CameraPreset, PresetView> = {
  room: { position: [0.2, 2.1, 6.0], target: [-0.1, 1.0, 0.3], fov: 60 },
  side: { position: [-8.2, 1.7, 1.4], target: [0, 1.0, 1.15], fov: 38 },
  top: { position: [0.2, 9.2, 1.9], target: [0.2, 0, 1.2], fov: 40 },
  bore: { position: [0.35, 1.5, 3.3], target: [0, 0.95, -0.2], fov: 52 },
  control: { position: [5.35, 1.75, 0.9], target: [2.0, 1.2, -1.1], fov: 68 },
}

export const CAMERA_LABELS: Record<CameraPreset, string> = {
  room: 'Room',
  side: 'Side',
  top: 'Top',
  bore: 'Bore',
  control: 'Control room',
}

export function isCameraPreset(v: string | null): v is CameraPreset {
  return v !== null && v in CAMERA_PRESETS
}

const GLIDE_RATE = 5
const ARRIVED_M = 0.01

/** Orbit controls plus a glide to the chosen preset. The first preset is applied at once. */
export function CameraRig({ preset }: { preset: CameraPreset }) {
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as OrbitControlsImpl | null
  const goal = useRef<PresetView>(CAMERA_PRESETS[preset])
  const gliding = useRef(false)
  const placed = useRef(false)

  useEffect(() => {
    goal.current = CAMERA_PRESETS[preset]
    if (!controls) return
    if (!placed.current) {
      placed.current = true
      camera.position.set(...goal.current.position)
      controls.target.set(...goal.current.target)
      controls.update()
    } else {
      gliding.current = true
    }
  }, [preset, controls, camera])

  useEffect(() => {
    if (!controls) return
    const stop = () => {
      gliding.current = false
    }
    controls.addEventListener('start', stop)
    return () => controls.removeEventListener('start', stop)
  }, [controls])

  useFrame((_, dt) => {
    if (!gliding.current || !controls) return
    const k = 1 - Math.exp(-GLIDE_RATE * Math.min(dt, 0.1))
    const g = goal.current
    camera.position.lerp(new Vector3(...g.position), k)
    controls.target.lerp(new Vector3(...g.target), k)
    const persp = camera as typeof camera & { fov?: number; updateProjectionMatrix(): void }
    if (persp.fov !== undefined) {
      persp.fov = MathUtils.lerp(persp.fov, g.fov, k)
      persp.updateProjectionMatrix()
    }
    controls.update()
    if (camera.position.distanceTo(new Vector3(...g.position)) < ARRIVED_M) gliding.current = false
  })

  return <OrbitControls makeDefault enableDamping dampingFactor={0.12} minDistance={0.8} maxDistance={14} maxPolarAngle={Math.PI * 0.495} />
}

export function CameraButtons({ value, onChange }: { value: CameraPreset; onChange: (p: CameraPreset) => void }) {
  return (
    <div className="scene__cams" role="group" aria-label="Camera">
      {(Object.keys(CAMERA_PRESETS) as CameraPreset[]).map((p) => (
        <button key={p} type="button" className={`scene__cam${p === value ? ' scene__cam--on' : ''}`} aria-pressed={p === value} onClick={() => onChange(p)}>
          {CAMERA_LABELS[p]}
        </button>
      ))}
    </div>
  )
}

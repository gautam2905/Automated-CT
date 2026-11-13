import { Environment, Lightformer } from '@react-three/drei'
import { Canvas, useThree } from '@react-three/fiber'
import { Suspense, useEffect, useRef, useState } from 'react'
import { NeutralToneMapping } from 'three'
import type { Snapshot } from '../api/types.gen'
import { useSession } from '../store/session'
import { FanBeam, LaserSheets } from './Beams'
import CTScanner from './CTScanner'
import Injector from './Injector'
import PatientFigure from './PatientFigure'
import RoomShell from './RoomShell'
import Table from './Table'
import Technologist from './Technologist'
import { CAMERA_PRESETS, CameraButtons, CameraRig, type CameraPreset } from './cameras'
import './scene.css'
import { wantsLowGraphics } from './graphicsMode'
import { useSmoothedSnapshotRef } from './useSmoothed'

// Matches the wall and ceiling colour so no view ever shows a dark gap beyond the room.
const BACKGROUND = '#dde3e6'

function Lighting() {
  return (
    <>
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={2.2} position={[0, 6, 0]} rotation-x={Math.PI / 2} scale={[10, 10, 1]} />
        <Lightformer form="rect" intensity={1.2} position={[-5, 3, 2]} rotation-y={Math.PI / 2} scale={[8, 3, 1]} />
        <Lightformer form="rect" intensity={1.2} position={[5, 3, 2]} rotation-y={-Math.PI / 2} scale={[8, 3, 1]} />
        <Lightformer form="rect" intensity={0.8} position={[0, 3, 7]} scale={[10, 3, 1]} />
      </Environment>
      <hemisphereLight args={['#ffffff', '#a9b6bd', 0.9]} />
      <directionalLight
        position={[3, 7, 5]}
        intensity={1.5}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-6}
        shadow-camera-right={7}
        shadow-camera-top={6}
        shadow-camera-bottom={-6}
        shadow-camera-near={0.5}
        shadow-camera-far={20}
        shadow-bias={-0.0004}
        shadow-normalBias={0.02}
      />
    </>
  )
}

/**
 * Everything inside the room. Eased values live in refs and are applied by frame callbacks, so React
 * re-renders this only for the discrete changes a new snapshot brings (stage, door, lights, beam).
 */
function World({ snapshot }: { snapshot: Snapshot }) {
  const target = useRef(snapshot)
  target.current = snapshot
  const sm = useSmoothedSnapshotRef(target)
  const { room, scanner, pose, injector } = snapshot
  return (
    <>
      <RoomShell doorOpen={room.door_open} warning={room.warning_light_on} />
      <CTScanner sm={sm} boreMm={scanner.bore_diameter_mm} isoMm={scanner.iso_height_mm} model={scanner.model} beamOn={scanner.beam_on} />
      <FanBeam sm={sm} beamOn={scanner.beam_on} isoMm={scanner.iso_height_mm} />
      <LaserSheets lasersOn={room.lasers_on} laserZMm={scanner.laser_z_mm} isoMm={scanner.iso_height_mm} />
      <Table sm={sm} />
      <PatientFigure sm={sm} stage={pose.stage} statureMm={pose.stature_mm} marks={pose.surface_marks} />
      <Technologist target={target} />
      <Injector sm={sm} target={target} present={injector != null} state={injector?.state ?? 'unloaded'} contrastMl={injector?.contrast_ml ?? 0} salineMl={injector?.saline_ml ?? 0} />
    </>
  )
}

const LOW_GRAPHICS_REDRAW_MS = 2000

/** In low-graphics mode the scene is redrawn on a timer, so a slow software renderer leaves the page time to respond. */
function SlowRedraw() {
  const invalidate = useThree((t) => t.invalidate)
  useEffect(() => {
    const timer = window.setInterval(invalidate, LOW_GRAPHICS_REDRAW_MS)
    return () => window.clearInterval(timer)
  }, [invalidate])
  return null
}

interface RoomSceneProps {
  initialCamera?: CameraPreset
}

/** The scan room in 3D, drawn from the latest snapshot. */
export default function RoomScene({ initialCamera = 'room' }: RoomSceneProps) {
  const snapshot = useSession((s) => s.snapshot)
  const [preset, setPreset] = useState<CameraPreset>(initialCamera)
  const view = CAMERA_PRESETS[initialCamera]
  const low = wantsLowGraphics()
  return (
    <section className="panel panel--scene" aria-label="Scan room">
      <Canvas
        frameloop={low ? 'demand' : 'always'}
        shadows={low ? false : 'percentage'}
        dpr={low ? 0.6 : [1, 1.5]}
        camera={{ position: view.position, fov: view.fov, near: 0.1, far: 60 }}
        gl={{ antialias: !low, preserveDrawingBuffer: low, toneMapping: NeutralToneMapping, toneMappingExposure: 1.05 }}
      >
        <color attach="background" args={[BACKGROUND]} />
        <Lighting />
        <Suspense fallback={null}>
          {snapshot ? <World snapshot={snapshot} /> : <RoomShell doorOpen={false} warning={false} />}
        </Suspense>
        <CameraRig preset={preset} />
        {low && <SlowRedraw />}
      </Canvas>
      <CameraButtons value={preset} onChange={setPreset} />
      {!snapshot && <p className="scene__empty">Start an exam to see the patient and staff.</p>}
    </section>
  )
}

// Dev-only page: renders <RoomScene/> from the sample snapshot. ?state=empty|standing|sitting|lying|prone|scan
// and ?camera=room|side|top|bore|control. Not part of the product.
import { Fragment, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import type { Snapshot } from '../api/types.gen'
import { useSession } from '../store/session'
import '../styles/app.css'
import sampleJson from '../test/sampleSnapshot.json'
import RoomScene from './RoomScene'
import { isCameraPreset } from './cameras'

const sample = sampleJson as unknown as Snapshot

function withState(state: string): Snapshot {
  const base = { ...sample, scanner: { ...sample.scanner, beam_on: false, tube_angle_deg: 40 } }
  const room = (r: Partial<Snapshot['room']>) => ({ ...base.room, ...r })
  const pose = (p: Partial<Snapshot['pose']>) => ({ ...base.pose, ...p })
  const table = (t: Partial<Snapshot['table']>) => ({ ...base.table, ...t })
  const idleInjector = base.injector ? { ...base.injector, state: 'loaded' as const, contrast_ml: 100, saline_ml: 50 } : null
  switch (state) {
    case 'empty':
      return { ...base, room: room({ door_open: true, warning_light_on: false, lasers_on: false, technologist_at: 'reception' }), pose: pose({ stage: 'away', iv_connected: false }), table: table({ long_mm: 0, height_mm: 800 }), injector: idleInjector }
    case 'standing':
      return { ...base, room: room({ door_open: true, warning_light_on: false, lasers_on: false, technologist_at: 'preparation' }), pose: pose({ stage: 'standing', iv_connected: false }), table: table({ long_mm: 0, height_mm: 700 }), injector: idleInjector }
    case 'sitting':
      return { ...base, room: room({ door_open: false, warning_light_on: false, lasers_on: false, technologist_at: 'preparation' }), pose: pose({ stage: 'sitting', iv_connected: false }), table: table({ long_mm: 0, height_mm: 600 }), injector: idleInjector }
    case 'proneup':
      return { ...base, room: room({ door_open: false, warning_light_on: false, lasers_on: true, technologist_at: 'gantry' }), pose: pose({ stage: 'lying', entry: 'head_first', orientation: 'prone', arms: 'up', iv_connected: false }), table: table({ long_mm: 600, height_mm: 880 }), injector: idleInjector }
    case 'prone':
      return { ...base, room: room({ door_open: false, warning_light_on: false, lasers_on: true, technologist_at: 'gantry' }), pose: pose({ stage: 'lying', entry: 'head_first', orientation: 'prone', arms: 'down', iv_connected: false }), table: table({ long_mm: 600, height_mm: 880 }), injector: idleInjector }
    case 'lying':
      return { ...base, room: room({ door_open: false, warning_light_on: false, lasers_on: true, technologist_at: 'gantry' }), pose: pose({ stage: 'lying', entry: 'feet_first', orientation: 'supine', arms: 'up', iv_connected: false }), table: table({ long_mm: 700, height_mm: 880 }), injector: idleInjector }
    default:
      return { ...base, scanner: { ...base.scanner, beam_on: true } }
  }
}

const params = new URLSearchParams(window.location.search)
const cameraParam = params.get('camera')
useSession.setState({ snapshot: withState(params.get('state') ?? 'scan') })
// Lets a screenshot script switch state while the page is running, to check the transitions.
;(window as unknown as { setSceneState: (name: string) => void }).setSceneState = (name) => useSession.setState({ snapshot: withState(name) })

const Wrapper = params.has('nostrict') ? Fragment : StrictMode
createRoot(document.getElementById('root') as HTMLElement).render(
  <Wrapper>
    <div style={{ width: '100vw', height: '100vh', display: 'grid', padding: 12, boxSizing: 'border-box' }}>
      <RoomScene initialCamera={isCameraPreset(cameraParam) ? cameraParam : 'room'} />
    </div>
  </Wrapper>,
)

import { create } from 'zustand'
import { fetchCatalog, type Catalog } from '../api/catalog'
import type { Action, Snapshot } from '../api/types.gen'
import { connect, type ServerMessage } from '../api/ws'

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'closed'
export interface ActionResult {
  ok: boolean
  error: string | null
}
export interface Socket {
  send(obj: unknown): void
  close(): void
}

/** The seed an exam starts with unless the user chooses another: it sets the patient's seeded variation. */
export const DEFAULT_SEED = 1

interface SessionData {
  catalog: Catalog | null
  modality: string | null
  protocolId: string | null
  patientId: string | null
  seed: number
  connection: ConnectionState
  socket: Socket | null
  snapshot: Snapshot | null
  lastError: string | null
  selectedStepId: string | null
  nextActionId: number
}

interface SessionActions {
  loadCatalog(): Promise<void>
  setModality(modality: string): void
  setProtocol(id: string): void
  setPatient(id: string): void
  setSeed(seed: number): void
  startExam(): void
  resetExam(): void
  send(action: Action): Promise<ActionResult>
  applyMessage(msg: ServerMessage): void
  handleClose(): void
  selectStep(id: string | null): void
}

export type SessionState = SessionData & SessionActions

// Resolvers of in-flight actions, keyed by action id.
const pending = new Map<number, (r: ActionResult) => void>()

export function initialSessionState(): SessionData {
  pending.clear()
  return {
    catalog: null,
    modality: null,
    protocolId: null,
    patientId: null,
    seed: DEFAULT_SEED,
    connection: 'idle',
    socket: null,
    snapshot: null,
    lastError: null,
    selectedStepId: null,
    nextActionId: 1,
  }
}

function settleAll(error: string): void {
  pending.forEach((resolve) => resolve({ ok: false, error }))
  pending.clear()
}

function firstProtocolId(catalog: Catalog | null, modality: string | null): string | null {
  return catalog?.protocols.find((p) => p.modality === modality)?.id ?? null
}

export const useSession = create<SessionState>()((set, get) => ({
  ...initialSessionState(),

  async loadCatalog() {
    try {
      const catalog = await fetchCatalog()
      const modality = catalog.modalities.find((m) => m.available)?.id ?? null
      set({
        catalog,
        modality,
        protocolId: firstProtocolId(catalog, modality),
        patientId: catalog.patients[0]?.id ?? null,
      })
    } catch (err) {
      set({ lastError: err instanceof Error ? err.message : 'Could not load the catalog' })
    }
  },

  setModality(modality) {
    set({ modality, protocolId: firstProtocolId(get().catalog, modality) })
  },
  setProtocol(id) {
    set({ protocolId: id })
  },
  setPatient(id) {
    set({ patientId: id })
  },
  setSeed(seed) {
    // The engine takes whole numbers from 0 up; anything else is ignored and the last good seed stays.
    if (Number.isSafeInteger(seed) && seed >= 0) set({ seed })
  },

  startExam() {
    const { modality, protocolId, patientId, seed } = get()
    if (!modality || !protocolId || !patientId) {
      set({ lastError: 'Choose a modality, exam and patient first' })
      return
    }
    if (get().connection === 'connecting') return
    let { socket } = get()
    if (!socket || get().connection !== 'open') {
      set({ connection: 'connecting', nextActionId: 1 })
      try {
        socket = connect(
          (msg) => get().applyMessage(msg),
          () => get().handleClose(),
          () => set({ connection: 'open' }),
        )
      } catch {
        set({ connection: 'closed', socket: null, lastError: 'Could not connect to the simulator' })
        return
      }
      set({ socket })
    }
    set({ lastError: null, snapshot: null, selectedStepId: null })
    socket.send({ type: 'start', modality, protocol_id: protocolId, patient_id: patientId, seed })
  },

  resetExam() {
    // The catalog and the choices in the top bar (exam, patient, seed) are kept for the next exam.
    get().socket?.close()
    settleAll('Exam reset')
    set({ socket: null, connection: 'idle', snapshot: null, selectedStepId: null, lastError: null, nextActionId: 1 })
  },

  send(action) {
    const { socket, connection, nextActionId } = get()
    if (!socket || connection !== 'open') {
      return Promise.resolve({ ok: false, error: 'Not connected to the simulator' })
    }
    set({ nextActionId: nextActionId + 1 })
    return new Promise<ActionResult>((resolve) => {
      pending.set(nextActionId, resolve)
      socket.send({ type: 'action', id: nextActionId, action })
    })
  },

  applyMessage(msg) {
    if (msg.type === 'snapshot') {
      set({ snapshot: msg.data })
    } else if (msg.type === 'result') {
      pending.get(msg.id)?.({ ok: msg.ok, error: msg.error })
      pending.delete(msg.id)
      set({ lastError: msg.ok ? null : msg.error })
    } else {
      set({ lastError: msg.message })
    }
  },

  handleClose() {
    settleAll('Connection closed')
    set({ connection: 'closed', socket: null })
  },

  selectStep(id) {
    set({ selectedStepId: id })
  },
}))

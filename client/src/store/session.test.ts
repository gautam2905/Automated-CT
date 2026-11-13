import { beforeEach, describe, expect, test, vi } from 'vitest'
import { connect } from '../api/ws'
import sampleJson from '../test/sampleSnapshot.json'
import type { Snapshot } from '../api/types.gen'
import { initialSessionState, useSession } from './session'

vi.mock('../api/ws', () => ({
  connect: vi.fn(() => ({ send: vi.fn(), close: vi.fn() })),
}))

const sample = sampleJson as unknown as Snapshot

beforeEach(() => {
  useSession.setState(initialSessionState())
})

describe('session store', () => {
  test('applyMessage stores a snapshot and a result resolves its promise', async () => {
    const sent: unknown[] = []
    useSession.setState({ socket: { send: (o: unknown) => sent.push(o), close() {} }, connection: 'open' })
    const p = useSession.getState().send({ type: 'perform', step_id: 'order_received' })
    useSession.getState().applyMessage({ type: 'snapshot', data: sample })
    useSession.getState().applyMessage({ type: 'result', id: 1, ok: false, error: 'Do the previous step first' })
    await expect(p).resolves.toEqual({ ok: false, error: 'Do the previous step first' })
    expect(sent).toEqual([{ type: 'action', id: 1, action: { type: 'perform', step_id: 'order_received' } }])
    expect(useSession.getState().snapshot?.session_id).toBe(sample.session_id)
    expect(useSession.getState().lastError).toBe('Do the previous step first')
  })

  test('closing the socket marks the connection closed and keeps the last snapshot', () => {
    useSession.setState({ snapshot: sample, connection: 'open' })
    useSession.getState().handleClose()
    expect(useSession.getState().connection).toBe('closed')
    expect(useSession.getState().socket).toBeNull()
    expect(useSession.getState().snapshot?.session_id).toBe(sample.session_id)
  })

  test('send without an open socket resolves with an error instead of hanging', async () => {
    await expect(useSession.getState().send({ type: 'abort' })).resolves.toEqual({
      ok: false,
      error: 'Not connected to the simulator',
    })
  })

  test('a closed socket resolves pending actions with an error', async () => {
    useSession.setState({ socket: { send() {}, close() {} }, connection: 'open' })
    const p = useSession.getState().send({ type: 'abort' })
    useSession.getState().handleClose()
    await expect(p).resolves.toEqual({ ok: false, error: 'Connection closed' })
  })

  test('a server error message is kept as lastError', () => {
    useSession.getState().applyMessage({ type: 'error', message: 'bad request' })
    expect(useSession.getState().lastError).toBe('bad request')
  })

  test('setModality picks the first exam of that modality', () => {
    useSession.setState({
      catalog: {
        modalities: [{ id: 'CT', label: 'CT', available: true }],
        protocols: [
          { id: 'a', title: 'A', modality: 'MRI', region: 'x', status: 'draft', source_url: '' },
          { id: 'b', title: 'B', modality: 'CT', region: 'x', status: 'complete', source_url: '' },
        ],
        patients: [],
        scanners: [],
      },
    })
    useSession.getState().setModality('CT')
    expect(useSession.getState().protocolId).toBe('b')
  })

  test('the seed starts at 1, takes whole numbers from 0 up and is sent with start', () => {
    const sent: unknown[] = []
    useSession.setState({
      modality: 'CT',
      protocolId: 'b',
      patientId: 'P-0001',
      socket: { send: (o: unknown) => sent.push(o), close() {} },
      connection: 'open',
    })
    expect(useSession.getState().seed).toBe(1)
    for (const bad of [-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) useSession.getState().setSeed(bad)
    expect(useSession.getState().seed).toBe(1)
    useSession.getState().setSeed(42)
    useSession.getState().startExam()
    expect(sent).toEqual([{ type: 'start', modality: 'CT', protocol_id: 'b', patient_id: 'P-0001', seed: 42 }])
    useSession.getState().resetExam()
    expect(useSession.getState().seed).toBe(42)              // the choices in the top bar survive a reset
  })

  test('startExam while connecting opens no second socket', () => {
    vi.mocked(connect).mockClear()
    useSession.setState({ modality: 'CT', protocolId: 'b', patientId: 'P-0001' })
    useSession.getState().startExam()
    expect(useSession.getState().connection).toBe('connecting')
    useSession.getState().startExam()
    expect(connect).toHaveBeenCalledTimes(1)
  })

  test('a throwing connect leaves the store closed so Start can be retried', () => {
    vi.mocked(connect).mockClear()
    vi.mocked(connect).mockImplementationOnce(() => {
      throw new Error('bad url')
    })
    useSession.setState({ modality: 'CT', protocolId: 'b', patientId: 'P-0001' })
    useSession.getState().startExam()
    expect(useSession.getState().connection).toBe('closed')
    expect(useSession.getState().socket).toBeNull()
    expect(useSession.getState().lastError).toBe('Could not connect to the simulator')
    useSession.getState().startExam()
    expect(connect).toHaveBeenCalledTimes(2)
  })
})

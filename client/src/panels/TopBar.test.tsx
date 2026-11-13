import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import sampleJson from '../test/sampleSnapshot.json'
import type { Catalog } from '../api/catalog'
import type { Snapshot } from '../api/types.gen'
import { initialSessionState, useSession } from '../store/session'
import TopBar from './TopBar'

const catalog: Catalog = {
  modalities: [
    { id: 'CT', label: 'CT', available: true },
    { id: 'MRI', label: 'MRI', available: false },
  ],
  protocols: [
    { id: 'ct.liver', title: 'CT Liver', modality: 'CT', region: 'abdomen', status: 'complete', source_url: '' },
    { id: 'mri.knee', title: 'MRI Knee', modality: 'MRI', region: 'knee', status: 'draft', source_url: '' },
  ],
  patients: [{ id: 'P-0001', label: 'Alex Sample' }],
  scanners: [{ id: 'ct1', label: 'CT 1' }],
}

beforeEach(() => {
  useSession.setState({
    ...initialSessionState(),
    catalog,
    modality: 'CT',
    protocolId: 'ct.liver',
    patientId: 'P-0001',
    loadCatalog: async () => {},
  })
})

describe('TopBar', () => {
  test('lists only exams of the chosen modality and disables MRI', () => {
    render(<TopBar />)
    const exam = screen.getByLabelText('Exam')
    const titles = within(exam).getAllByRole('option').map((o) => o.textContent)
    expect(titles).toEqual(['CT Liver'])
    const mri = within(screen.getByLabelText('Modality')).getByRole('option', { name: /MRI/ }) as HTMLOptionElement
    expect(mri.disabled).toBe(true)
    expect(mri.textContent).toContain('in progress')
  })

  test('Start exam sends a start message with the selections', () => {
    const send = vi.fn()
    useSession.setState({ socket: { send, close() {} }, connection: 'open' })
    render(<TopBar />)
    fireEvent.click(screen.getByRole('button', { name: 'Start exam' }))
    expect(send).toHaveBeenCalledWith({
      type: 'start',
      modality: 'CT',
      protocol_id: 'ct.liver',
      patient_id: 'P-0001',
      seed: 1,
    })
  })

  test('shows Reset once an exam runs and offers speeds 1, 4, 8, 20', () => {
    useSession.setState({ snapshot: sampleJson as unknown as Snapshot, connection: 'open' })
    render(<TopBar />)
    expect(screen.getByRole('button', { name: 'Reset' })).toBeTruthy()
    const speeds = within(screen.getByLabelText('Speed')).getAllByRole('option').map((o) => o.textContent)
    expect(speeds).toEqual(['1x', '4x', '8x', '20x'])
    expect(screen.getByText("Connected")).toBeTruthy()
  })

  test('changing speed sends a set_time_scale action', () => {
    const send = vi.fn()
    useSession.setState({ socket: { send, close() {} }, snapshot: sampleJson as unknown as Snapshot, connection: 'open' })
    render(<TopBar />)
    fireEvent.change(screen.getByLabelText('Speed'), { target: { value: '8' } })
    expect(send).toHaveBeenCalledWith({ type: 'action', id: 1, action: { type: 'set_time_scale', value: 8 } })
  })
  test('Start exam is disabled while connecting', () => {
    useSession.setState({ connection: 'connecting' })
    render(<TopBar />)
    expect((screen.getByRole('button', { name: 'Start exam' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('the seed', () => {
  test('the seed box starts at 1 and the chosen seed is sent with Start', () => {
    const send = vi.fn()
    useSession.setState({ socket: { send, close() {} }, connection: 'open' })
    render(<TopBar />)
    const seed = screen.getByLabelText('Seed') as HTMLInputElement
    expect(seed.value).toBe('1')
    fireEvent.change(seed, { target: { value: '7' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start exam' }))
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ type: 'start', patient_id: 'P-0001', seed: 7 }))
  })

  test('a seed that is not a whole number from 0 up is not taken, and the box shows the last good one again', () => {
    render(<TopBar />)
    const seed = screen.getByLabelText('Seed') as HTMLInputElement
    for (const bad of ['', '-3', '2.5']) {
      fireEvent.change(seed, { target: { value: bad } })
      expect(useSession.getState().seed).toBe(1)
    }
    fireEvent.blur(seed)
    expect(seed.value).toBe('1')
  })

  test('the seed cannot be changed while an exam runs', () => {
    useSession.setState({ snapshot: sampleJson as unknown as Snapshot, connection: 'open' })
    render(<TopBar />)
    expect((screen.getByLabelText('Seed') as HTMLInputElement).disabled).toBe(true)
  })
})

describe('Reset', () => {
  const sample = sampleJson as unknown as Snapshot
  const noneDone: Snapshot = {
    ...sample,
    stages: sample.stages.map((st) => ({ ...st, steps: st.steps.map((x) => ({ ...x, status: 'locked' as const })) })),
  }

  function running(snapshot: Snapshot) {
    const close = vi.fn()
    useSession.setState({ snapshot, connection: 'open', socket: { send() {}, close } })
    render(<TopBar />)
    return close
  }

  test('asks before discarding an exam in which a step is done, and Keep exam leaves it alone', () => {
    const close = running(sample)
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(screen.getByText(/Discard this exam\? It is not saved\./)).toBeTruthy()
    expect(close).not.toHaveBeenCalled()
    expect(useSession.getState().snapshot).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Keep exam' }))
    expect(useSession.getState().snapshot).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Reset' })).toBeTruthy()
  })

  test('Discard exam resets', () => {
    const close = running(sample)
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    fireEvent.click(screen.getByRole('button', { name: 'Discard exam' }))
    expect(close).toHaveBeenCalled()
    expect(useSession.getState().snapshot).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reset' })).toBeNull()
  })

  test('with no step done there is nothing to lose, so Reset acts at once', () => {
    running(noneDone)
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(useSession.getState().snapshot).toBeNull()
  })

  test('Reset is not where Start exam is: Start stays in place, disabled, and Reset sits at the end of the bar', () => {
    running(sample)
    const start = screen.getByRole('button', { name: 'Start exam' }) as HTMLButtonElement
    const reset = screen.getByRole('button', { name: 'Reset' })
    expect(start.disabled).toBe(true)
    expect(reset.className).toContain('topbar__reset')
    expect(reset.parentElement?.lastElementChild).toBe(reset)
    expect(start.nextElementSibling).not.toBe(reset)
    fireEvent.click(start)                                   // a second click on Start does nothing
    fireEvent.click(start)
    expect(useSession.getState().snapshot).not.toBeNull()
  })

  test('there is no Reset before an exam runs', () => {
    render(<TopBar />)
    expect(screen.queryByRole('button', { name: 'Reset' })).toBeNull()
    expect((screen.getByRole('button', { name: 'Start exam' }) as HTMLButtonElement).disabled).toBe(false)
  })
})

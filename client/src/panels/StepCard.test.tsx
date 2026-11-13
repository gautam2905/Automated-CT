import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import type { FieldView, Snapshot, StepView } from '../api/types.gen'
import sampleJson from '../test/sampleSnapshot.json'
import { initialSessionState, useSession } from '../store/session'
import FieldInput from './FieldInput'
import StepCard from './StepCard'

const heightField: FieldView = {
  key: 'height_mm',
  label: 'Table height',
  type: 'number',
  value: 700,
  default: 700,
  unit: 'mm',
  min: 480,
  max: 950,
  step: 1,
  source: 'protocol',
  editable: true,
}

function makeStep(over: Partial<StepView> = {}): StepView {
  return {
    id: 'table_height',
    stage_id: 'positioning',
    title: 'Set table height',
    actor: 'technologist',
    place: 'scan_room',
    info: 'Raise the table.',
    status: 'ready',
    blocked_by: [],
    fields: [heightField],
    results: [],
    action_label: 'Set height',
    ...over,
  }
}

const send = vi.fn()

beforeEach(() => {
  send.mockReset()
  send.mockResolvedValue({ ok: true, error: null })
  useSession.setState({ ...initialSessionState(), snapshot: sampleJson as unknown as Snapshot, send })
})

describe('StepCard', () => {
  test('a locked step shows why and cannot be performed', () => {
    const step = makeStep({ status: 'locked', blocked_by: ['Do "Consent" first'] })
    render(<StepCard step={step} />)
    expect(screen.getByText('Do "Consent" first')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Set height' }) as HTMLButtonElement).disabled).toBe(true)
  })

  test('a ready step sends perform', async () => {
    useSession.setState({ snapshot: { ...(sampleJson as unknown as Snapshot), stages: [] } })
    render(<StepCard step={makeStep()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Set height' }))
    await waitFor(() => expect(send).toHaveBeenCalledWith({ type: 'perform', step_id: 'table_height' }))
  })

  test('the button is disabled while another step is running', () => {
    render(<StepCard step={makeStep()} />)
    expect((screen.getByRole('button', { name: 'Set height' }) as HTMLButtonElement).disabled).toBe(true)
  })

  test('editing a number sends set_field with a number', async () => {
    useSession.setState({ snapshot: { ...(sampleJson as unknown as Snapshot), stages: [] } })
    render(<StepCard step={makeStep()} />)
    const input = screen.getByLabelText(/Table height/) as HTMLInputElement
    fireEvent.change(input, { target: { value: '620' } })
    fireEvent.blur(input)
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith({ type: 'set_field', step_id: 'table_height', key: 'height_mm', value: 620 }),
    )
  })

  test('a rejected edit shows the message and restores the value', async () => {
    useSession.setState({ snapshot: { ...(sampleJson as unknown as Snapshot), stages: [] } })
    send.mockResolvedValue({ ok: false, error: 'Table height must be 480 to 950 mm' })
    render(<StepCard step={makeStep()} />)
    const input = screen.getByLabelText(/Table height/) as HTMLInputElement
    fireEvent.change(input, { target: { value: '5000' } })
    fireEvent.blur(input)
    expect(await screen.findByText('Table height must be 480 to 950 mm')).toBeTruthy()
    expect(input.value).toBe('700')
  })

  test('assumed values are tagged', () => {
    const step = makeStep({ fields: [{ ...heightField, source: 'assumption' }] })
    render(<StepCard step={step} />)
    expect(screen.getByText('assumed')).toBeTruthy()
  })

  test('a running step shows the busy text and Stop sends abort', async () => {
    const snap = { ...(sampleJson as unknown as Snapshot), busy_text: 'Injecting contrast' }
    useSession.setState({ snapshot: snap })
    render(<StepCard step={makeStep({ status: 'running' })} />)
    expect(screen.getByText('Injecting contrast')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(send).toHaveBeenCalledWith({ type: 'abort' }))
  })

  test('status element carries the raw status and a plain word', () => {
    const { container } = render(<StepCard step={makeStep({ status: 'redo' })} />)
    const el = container.querySelector('[data-status]')
    expect(el?.getAttribute('data-status')).toBe('redo')
    expect(el?.textContent).toBe('Do again')
  })
})

function fieldBox(c: HTMLElement): HTMLInputElement {
  return c.querySelector('input') as HTMLInputElement
}

describe('FieldInput drafts', () => {
  test('an accepted but normalised edit shows the server value', async () => {
    const { container } = render(<FieldInput field={heightField} stepId="s" />)
    fireEvent.change(fieldBox(container), { target: { value: '700.4' } })
    expect(fieldBox(container).value).toBe('700.4')
    fireEvent.blur(fieldBox(container))
    await waitFor(() => expect(fieldBox(container).value).toBe('700'))
  })

  test('typed text survives a new server value until blur, then the server value shows', async () => {
    const { container, rerender } = render(<FieldInput field={heightField} stepId="s" />)
    fireEvent.focus(fieldBox(container))
    fireEvent.change(fieldBox(container), { target: { value: '65' } })
    rerender(<FieldInput field={{ ...heightField, value: 650 }} stepId="s" />)
    expect(fieldBox(container).value).toBe('65')
    send.mockResolvedValue({ ok: false, error: 'Table height must be 480 to 950 mm' })
    fireEvent.blur(fieldBox(container))
    await waitFor(() => expect(fieldBox(container).value).toBe('650'))
  })

  test('typing again clears the error and an equal number sends nothing', async () => {
    send.mockResolvedValueOnce({ ok: false, error: 'bad' })
    const { container, findByText, queryByText } = render(<FieldInput field={heightField} stepId="s" />)
    fireEvent.change(fieldBox(container), { target: { value: '5000' } })
    fireEvent.blur(fieldBox(container))
    await findByText('bad')
    fireEvent.change(fieldBox(container), { target: { value: '700.0' } })
    expect(queryByText('bad')).toBeNull()
    send.mockClear()
    fireEvent.blur(fieldBox(container))
    expect(send).not.toHaveBeenCalled()
    await waitFor(() => expect(fieldBox(container).value).toBe('700'))
  })
})

test('a late commit does not wipe newer typing', async () => {
  let resolveFirst: (r: { ok: boolean; error: string | null }) => void = () => {}
  send.mockReset()
  send.mockReturnValueOnce(new Promise((r) => { resolveFirst = r }))
  const { container } = render(<FieldInput field={heightField} stepId="s" />)
  fireEvent.change(fieldBox(container), { target: { value: '650' } })
  fireEvent.blur(fieldBox(container))
  fireEvent.focus(fieldBox(container))
  fireEvent.change(fieldBox(container), { target: { value: '660' } })
  resolveFirst({ ok: false, error: 'late message' })
  await new Promise((r) => setTimeout(r, 0))
  expect(fieldBox(container).value).toBe('660')
  expect(container.textContent).not.toContain('late message')
})

test('a thrown send shows as the field message', async () => {
  send.mockReset()
  send.mockRejectedValue(new Error('socket exploded'))
  const { container, findByText } = render(<FieldInput field={heightField} stepId="s" />)
  fireEvent.change(fieldBox(container), { target: { value: '650' } })
  fireEvent.blur(fieldBox(container))
  await findByText('socket exploded')
})

describe('doing a done step again', () => {
  const idle = { ...(sampleJson as unknown as Snapshot), stages: [] }

  test('a done step that can be repeated offers "Do again", which sends perform', async () => {
    useSession.setState({ snapshot: idle })
    render(<StepCard step={makeStep({ status: 'done', repeatable: true })} />)
    const button = screen.getByRole('button', { name: 'Do again' }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
    expect(screen.queryByRole('button', { name: 'Set height' })).toBeNull()
    fireEvent.click(button)
    await waitFor(() => expect(send).toHaveBeenCalledWith({ type: 'perform', step_id: 'table_height' }))
  })

  test('"Do again" is disabled while any step is running', () => {
    render(<StepCard step={makeStep({ status: 'done', repeatable: true })} />)
    expect((screen.getByRole('button', { name: 'Do again' }) as HTMLButtonElement).disabled).toBe(true)
  })

  test('a done step that cannot be repeated keeps its own label and stays disabled', () => {
    useSession.setState({ snapshot: idle })
    for (const repeatable of [false, undefined]) {
      const { unmount } = render(<StepCard step={makeStep({ status: 'done', repeatable })} />)
      expect((screen.getByRole('button', { name: 'Set height' }) as HTMLButtonElement).disabled).toBe(true)
      expect(screen.queryByRole('button', { name: 'Do again' })).toBeNull()
      unmount()
    }
  })

  test('a done step that can no longer be repeated says why', () => {
    useSession.setState({ snapshot: idle })
    const why = 'The injection has started, so "Set table height" cannot be done again'
    render(<StepCard step={makeStep({ status: 'done', repeatable: false, blocked_by: [why] })} />)
    expect(screen.getByText(why)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Do again' })).toBeNull()
    expect((screen.getByRole('button', { name: 'Set height' }) as HTMLButtonElement).disabled).toBe(true)
  })

  test('a step waiting to be redone that is still blocked says why and cannot be performed yet', () => {
    useSession.setState({ snapshot: idle })
    render(<StepCard step={makeStep({ status: 'redo', repeatable: true, blocked_by: ['Do "Leave room" first'] })} />)
    expect(screen.getByText('Do "Leave room" first')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Set height' }) as HTMLButtonElement).disabled).toBe(true)
  })

  test('a step waiting to be redone keeps its own label and can be performed', () => {
    useSession.setState({ snapshot: idle })
    render(<StepCard step={makeStep({ status: 'redo', repeatable: true })} />)
    expect((screen.getByRole('button', { name: 'Set height' }) as HTMLButtonElement).disabled).toBe(false)
  })
})

import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, test } from 'vitest'
import type { Snapshot } from '../api/types.gen'
import sampleJson from '../test/sampleSnapshot.json'
import { initialSessionState, useSession } from '../store/session'
import ProcedurePanel from './ProcedurePanel'

beforeEach(() => {
  useSession.setState({ ...initialSessionState(), snapshot: sampleJson as unknown as Snapshot })
})

describe('ProcedurePanel', () => {
  test('stage headers count completed steps and the current stage is open', () => {
    render(<ProcedurePanel />)
    expect(screen.getByRole('button', { name: /Request/ }).textContent).toContain('3 of 3 done')
    const contrast = screen.getByRole('button', { name: /Contrast/ })
    expect(contrast.textContent).toContain('0 of 3 done')
    expect(contrast.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('button', { name: /Request/ }).getAttribute('aria-expanded')).toBe('false')
    expect(document.querySelector('[data-step="inject_and_arterial"]')).not.toBeNull()
    expect(document.querySelector('[data-step="order_received"]')).toBeNull()
  })

  test('a header toggles its stage', () => {
    render(<ProcedurePanel />)
    fireEvent.click(screen.getByRole('button', { name: /Request/ }))
    expect(document.querySelector('[data-step="order_received"]')).not.toBeNull()
  })

  test('a stage stays open after its last step finishes', () => {
    render(<ProcedurePanel />)
    const snap = sampleJson as unknown as Snapshot
    const finished = {
      ...snap,
      stages: snap.stages.map((st) =>
        st.id === snap.stages.find((x) => x.steps.some((y) => y.status !== 'done'))?.id
          ? { ...st, steps: st.steps.map((x) => ({ ...x, status: 'done' as const })) }
          : st,
      ),
    }
    act(() => useSession.setState({ snapshot: finished }))
    expect(screen.getByRole('button', { name: /Contrast/ }).getAttribute('aria-expanded')).toBe('true')
    expect(document.querySelector('[data-step="inject_and_arterial"]')).not.toBeNull()
  })

  test('shows a waiting note without a snapshot', () => {
    useSession.setState({ snapshot: null })
    const { container } = render(<ProcedurePanel />)
    expect(within(container).getByText(/Start an exam/)).toBeTruthy()
  })
})

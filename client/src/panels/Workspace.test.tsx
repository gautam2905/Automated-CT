import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import Workspace from './Workspace'

function show() {
  return render(
    <Workspace
      steps={<input aria-label="Table height" defaultValue="850" />}
      room={<h2>Room</h2>}
      console={<h2>Readings</h2>}
    />,
  )
}

const button = (name: string) => screen.getByRole('button', { name }) as HTMLButtonElement
// Found by role, which leaves out what is hidden: a side that is put away stays in the page, out of sight.
const shown = (name: string) => screen.queryByRole('heading', { name })

describe('Workspace', () => {
  test('the steps, the room and the console are all shown at first, with a control to hide each side', () => {
    const { container } = show()
    expect(screen.getByRole('textbox', { name: 'Table height' })).toBeTruthy()
    expect(shown('Room')).toBeTruthy()
    expect(shown('Readings')).toBeTruthy()
    for (const name of ['Hide steps', 'Hide console']) {
      expect(button(name).getAttribute('aria-expanded')).toBe('true')
      expect(container.querySelector(`#${button(name).getAttribute('aria-controls')}`)).toBeTruthy()
    }
    expect(container.querySelector('main')?.dataset).toMatchObject({ steps: 'open', console: 'open' })
  })

  test('hiding the steps puts them away, names what is hidden, and the control turns into the way back', () => {
    const { container } = show()
    fireEvent.click(button('Hide steps'))
    expect(screen.queryByRole('textbox', { name: 'Table height' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Hide steps' })).toBeNull()
    const back = button('Show steps')
    expect(back.getAttribute('aria-expanded')).toBe('false')
    expect(back.textContent).toContain('Steps')                      // the rail says what it brings back
    expect(container.querySelector('main')?.dataset).toMatchObject({ steps: 'closed', console: 'open' })
    expect(shown('Readings')).toBeTruthy()                           // the other side is untouched
    expect(button('Hide console').textContent).not.toContain('Console')   // an open side needs no name on its handle
  })

  test('a hidden side stays as it was: what was typed is still there when it is shown again', () => {
    show()
    fireEvent.change(screen.getByRole('textbox', { name: 'Table height' }), { target: { value: '872' } })
    fireEvent.click(button('Hide steps'))
    fireEvent.click(button('Show steps'))
    expect((screen.getByRole('textbox', { name: 'Table height' }) as HTMLInputElement).value).toBe('872')
  })

  test('the console hides and returns on its own, and both sides can be away at once', () => {
    const { container } = show()
    fireEvent.click(button('Hide console'))
    expect(shown('Readings')).toBeNull()
    expect(screen.getByRole('textbox', { name: 'Table height' })).toBeTruthy()
    fireEvent.click(button('Hide steps'))
    expect(container.querySelector('main')?.dataset).toMatchObject({ steps: 'closed', console: 'closed' })
    expect(shown('Room')).toBeTruthy()                               // the room is never hidden
    fireEvent.click(button('Show console'))
    expect(shown('Readings')).toBeTruthy()
    expect(container.querySelector('main')?.dataset).toMatchObject({ steps: 'closed', console: 'open' })
  })
})

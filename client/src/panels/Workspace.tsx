import { useState, type ReactNode } from 'react'

type Side = 'steps' | 'console'

/** What each side is called on its rail and by its control, when it is open and when it is put away. */
const WORDS: Record<Side, { name: string; hide: string; show: string }> = {
  steps: { name: 'Steps', hide: 'Hide steps', show: 'Show steps' },
  console: { name: 'Console', hide: 'Hide console', show: 'Show console' },
}

interface Props {
  steps: ReactNode
  room: ReactNode
  console: ReactNode
}

interface ToggleProps {
  side: Side
  open: boolean
  onToggle: () => void
}

/**
 * The bar between a side and the room. While the side is open it is a slim handle; once the side is put away
 * it is a rail that names what it brings back. The arrow always points the way the side will move.
 */
function SideToggle({ side, open, onToggle }: ToggleProps) {
  const words = WORDS[side]
  const pointsLeft = (side === 'steps') === open
  return (
    <button
      type="button"
      className={`rail rail--${side}`}
      aria-expanded={open}
      aria-controls={`workspace-${side}`}
      aria-label={open ? words.hide : words.show}
      title={open ? words.hide : words.show}
      onClick={onToggle}
    >
      <span className="rail__tab">
        <svg className="rail__arrow" viewBox="0 0 8 14" width="8" height="14" aria-hidden="true">
          <path d={pointsLeft ? 'M6.5 1.5 1.5 7l5 5.5' : 'M1.5 1.5 6.5 7l-5 5.5'} />
        </svg>
      </span>
      {open ? null : <span className="rail__name">{words.name}</span>}
    </button>
  )
}

/**
 * The three parts of the page: the steps, the room and the console. Either side can be put away to give the
 * rest more room. A side that is put away is hidden, not removed, so it is as it was when it comes back.
 */
export default function Workspace({ steps, room, console: readings }: Props) {
  const [open, setOpen] = useState<Record<Side, boolean>>({ steps: true, console: true })
  const toggle = (side: Side) => () => setOpen((now) => ({ ...now, [side]: !now[side] }))
  const state = (side: Side) => (open[side] ? 'open' : 'closed')
  return (
    <main className="app__body" data-steps={state('steps')} data-console={state('console')}>
      <div id="workspace-steps" className="app__side app__side--steps" hidden={!open.steps}>
        {steps}
      </div>
      <SideToggle side="steps" open={open.steps} onToggle={toggle('steps')} />
      <div className="app__room">{room}</div>
      <SideToggle side="console" open={open.console} onToggle={toggle('console')} />
      <div id="workspace-console" className="app__side app__side--console" hidden={!open.console}>
        {readings}
      </div>
    </main>
  )
}

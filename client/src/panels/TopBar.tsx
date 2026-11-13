import { useState, type ReactNode } from 'react'
import { useSession } from '../store/session'

const SPEEDS = [1, 4, 8, 20]
const CONNECTION_WORD: Record<string, string | undefined> = {
  idle: undefined,
  connecting: 'Connecting…',
  open: 'Connected',
  closed: 'Disconnected',
}
const SEED_HELP =
  'Chooses the seeded variation: how far off-centre the patient lies down, and the synthetic age and sex. ' +
  'The same seed and patient give the same exam.'

interface ChoiceProps {
  label: string
  value: string
  disabled: boolean
  onChange: (value: string) => void
  children: ReactNode
}

function Choice({ label, value, disabled, onChange, children }: ChoiceProps) {
  return (
    <label className="topbar__field">
      {label}
      <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
    </label>
  )
}

/** Modality, exam and patient: fixed once an exam runs. */
function ExamChoices({ running }: { running: boolean }) {
  const s = useSession()
  const protocols = (s.catalog?.protocols ?? []).filter((p) => p.modality === s.modality)
  return (
    <>
      <Choice label="Modality" value={s.modality ?? ''} disabled={running} onChange={s.setModality}>
        {(s.catalog?.modalities ?? []).map((m) => (
          <option key={m.id} value={m.id} disabled={!m.available}>
            {m.available ? m.label : `${m.label} (in progress)`}
          </option>
        ))}
      </Choice>
      <Choice label="Exam" value={s.protocolId ?? ''} disabled={running} onChange={s.setProtocol}>
        {protocols.map((p) => (
          <option key={p.id} value={p.id}>
            {p.title}
          </option>
        ))}
      </Choice>
      <Choice label="Patient" value={s.patientId ?? ''} disabled={running} onChange={s.setPatient}>
        {(s.catalog?.patients ?? []).map((p) => (
          <option key={p.id} value={p.id}>
            {p.label}
          </option>
        ))}
      </Choice>
    </>
  )
}

/** The seed sent with Start. What is typed shows while typing; only a whole number from 0 up is taken. */
function SeedInput({ disabled }: { disabled: boolean }) {
  const seed = useSession((s) => s.seed)
  const setSeed = useSession((s) => s.setSeed)
  const [draft, setDraft] = useState<string | null>(null)
  return (
    <label className="topbar__field" title={SEED_HELP}>
      Seed
      <input
        type="number"
        min={0}
        step={1}
        disabled={disabled}
        value={draft ?? String(seed)}
        onChange={(e) => {
          setDraft(e.target.value)
          setSeed(e.target.value.trim() === '' ? Number.NaN : Number(e.target.value))
        }}
        onBlur={() => setDraft(null)}
      />
    </label>
  )
}

/**
 * Reset throws the exam away (sessions are not saved). It sits at the far end of the bar, away from
 * "Start exam", and asks first once any step has been done.
 */
function ResetControl() {
  const resetExam = useSession((s) => s.resetExam)
  const anyDone = useSession((s) => s.snapshot?.stages.some((st) => st.steps.some((x) => x.status === 'done')) ?? false)
  const [asking, setAsking] = useState(false)
  if (!asking) {
    return (
      <button type="button" className="btn btn--ghost topbar__reset" onClick={() => (anyDone ? setAsking(true) : resetExam())}>
        Reset
      </button>
    )
  }
  return (
    <span className="topbar__reset topbar__confirm" role="group" aria-label="Confirm reset">
      Discard this exam? It is not saved.
      <button type="button" className="btn btn--danger" onClick={resetExam}>
        Discard exam
      </button>
      <button type="button" className="btn btn--ghost" onClick={() => setAsking(false)}>
        Keep exam
      </button>
    </span>
  )
}

export default function TopBar() {
  const s = useSession()
  const running = s.snapshot !== null
  const speed = s.snapshot?.clock.time_scale ?? 1
  const cannotStart = running || !s.protocolId || !s.patientId || s.connection === 'connecting'
  return (
    <header className="topbar">
      <h1 className="topbar__title">CT scan room</h1>
      <ExamChoices running={running} />
      <SeedInput disabled={running} />
      <Choice label="Speed" value={String(speed)} disabled={!running} onChange={(v) => void s.send({ type: 'set_time_scale', value: Number(v) })}>
        {SPEEDS.map((v) => (
          <option key={v} value={v}>
            {v}x
          </option>
        ))}
      </Choice>
      <button type="button" className="btn" disabled={cannotStart} onClick={s.startExam}>
        Start exam
      </button>
      {CONNECTION_WORD[s.connection] && (
        <span className={`topbar__conn topbar__conn--${s.connection}`} data-state={s.connection} role="status">
          {CONNECTION_WORD[s.connection]}
        </span>
      )}
      {s.lastError && (
        <span className="topbar__error" role="alert">
          {s.lastError}
        </span>
      )}
      {running && <ResetControl />}
    </header>
  )
}

import type { StepView } from '../api/types.gen'
import { useSession } from '../store/session'
import FieldInput from './FieldInput'

const STATUS_WORD: Record<StepView['status'], string> = {
  locked: 'Not yet',
  ready: 'Ready',
  running: 'In progress',
  done: 'Done',
  redo: 'Do again',
}

const ACTOR_WORD: Record<StepView['actor'], string> = {
  radiologist: 'Radiologist',
  nurse: 'Nurse',
  technologist: 'Technologist',
  patient: 'Patient',
  scanner: 'Scanner',
}

const PLACE_WORD: Record<StepView['place'], string> = {
  reception: 'reception',
  preparation: 'preparation room',
  scan_room: 'scan room',
  console: 'console',
}

export const REPEAT_LABEL = 'Do again'

/** A done step the engine still allows to be repeated: its changed values take effect when it is done again. */
export function canRepeat(step: StepView): boolean {
  return step.status === 'done' && step.repeatable === true
}

export default function StepCard({ step }: { step: StepView }) {
  const send = useSession((s) => s.send)
  const selected = useSession((s) => s.selectedStepId === step.id)
  const selectStep = useSession((s) => s.selectStep)
  const busyText = useSession((s) => s.snapshot?.busy_text)
  const anyRunning = useSession((s) => s.snapshot?.stages.some((st) => st.steps.some((x) => x.status === 'running')) ?? false)
  const isRunning = step.status === 'running'
  const repeat = canRepeat(step)
  const canPerform = (step.status === 'ready' || step.status === 'redo' || repeat) && !anyRunning && !isRunning
  const blockedBy = step.status === 'locked' ? (step.blocked_by ?? []) : []

  return (
    <article
      className={`step${selected ? ' step--selected' : ''}`}
      data-step={step.id}
      onClick={() => selectStep(step.id)}
    >
      <header className="step__head">
        <h4 className="step__title">{step.title}</h4>
        <span className="step__status" data-status={step.status}>
          {STATUS_WORD[step.status]}
        </span>
      </header>
      <p className="step__who">
        {ACTOR_WORD[step.actor]} · {PLACE_WORD[step.place]}
      </p>
      {step.info ? <p className="step__info">{step.info}</p> : null}
      {blockedBy.length > 0 ? (
        <ul className="step__blocked">
          {blockedBy.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
      {(step.fields ?? []).map((f) => (
        <FieldInput key={f.key} field={f} stepId={step.id} locked={anyRunning} />
      ))}
      {(step.results ?? []).length > 0 ? (
        <dl className="step__results">
          {(step.results ?? []).map((r) => (
            <div key={r.label} className={r.alert ? 'step__result step__result--alert' : 'step__result'}>
              <dt>{r.label}</dt>
              <dd>{r.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {isRunning ? (
        <div className="step__busy">
          <span>{busyText || 'Working'}</span>
          <button type="button" className="btn btn--ghost" onClick={() => void send({ type: 'abort' })}>
            Stop
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="btn step__action"
          disabled={!canPerform}
          onClick={() => void send({ type: 'perform', step_id: step.id })}
        >
          {repeat ? REPEAT_LABEL : step.action_label || 'Do step'}
        </button>
      )}
    </article>
  )
}

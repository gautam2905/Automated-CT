import { useEffect, useState } from 'react'
import type { StageView } from '../api/types.gen'
import { useSession } from '../store/session'
import StepCard from './StepCard'
import './procedure.css'

function currentStageId(stages: StageView[]): string | null {
  return stages.find((s) => s.steps.some((x) => x.status !== 'done'))?.id ?? null
}

export default function ProcedurePanel() {
  const stages = useSession((s) => s.snapshot?.stages)
  const [overrides, setOverrides] = useState<Record<string, boolean>>({})
  // Stages that have been the current one stay open until the user closes them, so a finished step's results stay readable.
  const [visited, setVisited] = useState<Record<string, boolean>>({})
  const current = stages ? currentStageId(stages) : null
  useEffect(() => {
    if (current) setVisited((v) => (v[current] ? v : { ...v, [current]: true }))
  }, [current])

  if (!stages) {
    return (
      <section className="panel panel--procedure" aria-label="Procedure">
        <p className="panel__note">Start an exam to see its procedure.</p>
      </section>
    )
  }
  return (
    <section className="panel panel--procedure" aria-label="Procedure">
      {stages.map((stage) => {
        const done = stage.steps.filter((x) => x.status === 'done').length
        const open = overrides[stage.id] ?? (visited[stage.id] === true || stage.id === current)
        const bodyId = `stage-${stage.id}`
        return (
          <div key={stage.id} className="stage" data-stage={stage.id}>
            <h3 className="stage__heading">
              <button
                type="button"
                className="stage__toggle"
                aria-expanded={open}
                aria-controls={bodyId}
                onClick={() => setOverrides((o) => ({ ...o, [stage.id]: !open }))}
              >
                <span className="stage__title">{stage.title}</span>
                <span className="stage__count">
                  {done} of {stage.steps.length} done
                </span>
              </button>
            </h3>
            {open ? (
              <div id={bodyId} className="stage__body">
                {stage.steps.map((step) => (
                  <StepCard key={step.id} step={step} />
                ))}
              </div>
            ) : null}
          </div>
        )
      })}
    </section>
  )
}

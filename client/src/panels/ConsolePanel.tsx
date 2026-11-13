import { useState } from 'react'
import ContrastTab from '../console/ContrastTab'
import DoseTab from '../console/DoseTab'
import ExamTab from '../console/ExamTab'
import ImagesTab from '../console/ImagesTab'
import LogTab from '../console/LogTab'
import '../console/console.css'
import { useSession } from '../store/session'

const TABS = [
  { id: 'exam', label: 'Exam', Body: ExamTab },
  { id: 'images', label: 'Images', Body: ImagesTab },
  { id: 'contrast', label: 'Contrast', Body: ContrastTab },
  { id: 'dose', label: 'Dose', Body: DoseTab },
  { id: 'log', label: 'Log', Body: LogTab },
] as const

export default function ConsolePanel() {
  const snapshot = useSession((s) => s.snapshot)
  const [active, setActive] = useState<(typeof TABS)[number]['id']>('exam')
  const tab = TABS.find((t) => t.id === active) ?? TABS[0]
  return (
    <section className="panel panel--console console" aria-label="Console">
      <div role="tablist" aria-label="Console" className="console__tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`console-tab-${t.id}`}
            aria-selected={t.id === active}
            aria-controls="console-body"
            className="console__tab"
            onClick={() => setActive(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="console-body" aria-labelledby={`console-tab-${active}`}>
        {snapshot ? <tab.Body snapshot={snapshot} /> : <p className="panel__note">Start an exam to use the console.</p>}
      </div>
    </section>
  )
}

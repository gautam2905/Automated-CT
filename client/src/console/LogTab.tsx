import type { LogEntry, Snapshot } from '../api/types.gen'
import { formatClock } from './topogramMath'

function Text({ entry }: { entry: LogEntry }) {
  return entry.kind === 'voice' ? <em>{`“${entry.text}”`}</em> : <span>{entry.text}</span>
}

export default function LogTab({ snapshot }: { snapshot: Snapshot }) {
  const entries = [...(snapshot.log ?? [])].reverse()
  if (entries.length === 0) return <p className="panel__note">Nothing logged yet.</p>
  return (
    <ul className="log">
      {entries.map((e, i) => (
        <li key={entries.length - 1 - i} className={`log__item log__item--${e.kind}`}>
          <span className="log__time">{formatClock(e.t_s)}</span>
          <Text entry={e} />
        </li>
      ))}
    </ul>
  )
}

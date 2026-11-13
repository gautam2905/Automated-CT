import type { Snapshot } from '../api/types.gen'
import { useSession } from '../store/session'
import SliceViewer from './SliceViewer'
import TopogramViewer from './TopogramViewer'

export default function ImagesTab({ snapshot }: { snapshot: Snapshot }) {
  const send = useSession((s) => s.send)
  const { topograms = [], series = [] } = snapshot.console
  return (
    <div>
      <label className="console__row">
        <input
          type="checkbox"
          checked={snapshot.show_reference ?? false}
          onChange={(e) => void send({ type: 'set_reference', on: e.target.checked })}
        />
        Show reference anatomy
      </label>
      {topograms.length === 0 ? (
        <p className="panel__note">No topogram yet.</p>
      ) : (
        <div className="viewer viewer__pair">
          {topograms.map((t) => (
            <div key={t.view}>
              <div className="viewer__caption">{t.view === 'AP' ? 'AP' : 'Lateral'}</div>
              <TopogramViewer topogram={t} snapshot={snapshot} interactive={t.view === 'AP'} />
            </div>
          ))}
        </div>
      )}
      <h3>Series</h3>
      <SliceViewer series={series} />
    </div>
  )
}

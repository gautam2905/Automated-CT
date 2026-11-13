import { useState } from 'react'
import type { SeriesView } from '../api/types.gen'

export function sliceUrl(series: SeriesView, plane: string, index: number): string {
  return series.image_url_template.replace('{plane}', plane).replace('{index}', String(index))
}

function SliceImage({ series, plane, index }: { series: SeriesView; plane: string; index: number }) {
  return (
    <img
      className="viewer__slice"
      src={sliceUrl(series, plane, index)}
      alt={`${series.label} ${plane} image ${index + 1}`}
    />
  )
}

export default function SliceViewer({ series }: { series: SeriesView[] }) {
  const [seriesId, setSeriesId] = useState<string | null>(null)
  const [plane, setPlane] = useState<string>('axial')
  const [index, setIndex] = useState(0)
  const current = series.find((s) => s.id === seriesId) ?? series.find((s) => s.status === 'done') ?? series[0]
  if (!current) return null
  const recon = current.recons.find((r) => r.plane === plane) ?? current.recons[0]
  const count = recon?.image_count ?? 0
  const ready = current.status === 'done' && recon?.ready === true
  const shown = Math.min(index, Math.max(0, count - 1))

  return (
    <div className="viewer">
      <div role="tablist" aria-label="Series" className="series-tabs">
        {series.map((s) => (
          <button key={s.id} role="tab" aria-selected={s.id === current.id} onClick={() => setSeriesId(s.id)}>
            {s.label}
          </button>
        ))}
      </div>
      <div className="console__row">
        <select
          aria-label="Reconstruction"
          value={recon?.plane ?? ''}
          disabled={current.recons.length === 0}
          onChange={(e) => setPlane(e.target.value)}
        >
          {current.recons.map((r) => (
            <option key={r.plane} value={r.plane}>
              {`${r.plane}, ${r.thickness_mm} mm, ${r.kernel}`}
            </option>
          ))}
        </select>
        {ready && (
          <span>
            {shown + 1} / {count}
          </span>
        )}
      </div>
      {ready && recon ? (
        <>
          <input
            type="range"
            aria-label="Image number"
            min={0}
            max={Math.max(0, count - 1)}
            value={shown}
            onChange={(e) => setIndex(Number(e.target.value))}
          />
          <SliceImage series={current} plane={recon.plane} index={shown} />
        </>
      ) : (
        <div className="viewer__empty">Not acquired yet</div>
      )}
    </div>
  )
}

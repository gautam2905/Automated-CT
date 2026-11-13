import type { Snapshot } from '../api/types.gen'

const round = (v: number) => Math.round(v * 10) / 10

/** What the total is and is not: said beside it, because the numbers alone look measured. */
export const DOSE_NOTE =
  'A model estimate: the scanner’s dose calibration and its tube-current adaptation are assumed. The total ' +
  'leaves out the topograms, the monitoring slice and the bolus-monitoring scans. A scan that was stopped ' +
  'part-way or scanned again keeps what it delivered in the total, and has a row of its own above.'

export default function DoseTab({ snapshot }: { snapshot: Snapshot }) {
  const { series = [], dose } = snapshot.console
  return (
    <div>
      <table className="dose-table">
        <thead>
          <tr>
            <th>Series</th>
            <th>CTDIvol predicted (mGy)</th>
            <th>CTDIvol delivered (mGy)</th>
            <th>DLP predicted (mGy·cm)</th>
            <th>DLP delivered (mGy·cm)</th>
          </tr>
        </thead>
        <tbody>
          {series.map((s) => {
            const f = Math.min(1, Math.max(0, s.scanned_fraction))
            return (
              <tr key={s.id}>
                <td>{s.label}</td>
                <td>{round(s.plan.ctdi_vol_mgy)}</td>
                <td>{round(s.plan.ctdi_vol_mgy * f)}</td>
                <td>{round(s.plan.dlp_mgycm)}</td>
                <td>{round(s.plan.dlp_mgycm * f)}</td>
              </tr>
            )
          })}
          {/* Exposures that no series row shows any more, so that the last column adds up to the total. */}
          {(dose.extra_exposures ?? []).map((e, i) => (
            <tr key={`extra-${i}`} className="dose-table__extra">
              <td colSpan={4}>
                {e.label}, {e.what}
              </td>
              <td>{round(e.dlp_mgycm)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        <strong>Total DLP: {round(dose.total_dlp_mgycm)} mGy·cm</strong>
        <span className="console__tag">assumed</span>
      </p>
      <p className="panel__note" data-testid="dose-note">
        {DOSE_NOTE}
      </p>
      {(dose.alerts ?? []).length > 0 && (
        <ul className="console__alert">
          {dose.alerts?.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

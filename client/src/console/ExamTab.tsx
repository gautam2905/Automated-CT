import type { Snapshot } from '../api/types.gen'
import { formatClock } from './topogramMath'

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

function Estimated({ snapshot, field, text }: { snapshot: Snapshot; field: string; text: string }) {
  const estimated = snapshot.patient.estimated_fields.includes(field)
  return estimated ? <span className="console__estimated">{text} (estimated)</span> : <>{text}</>
}

/** Age and sex are not in the scan data: when the record lists them as not known, they are invented values. */
function AgeAndSex({ snapshot }: { snapshot: Snapshot }) {
  const { age, sex, estimated_fields: unknown } = snapshot.patient
  const text = `${age} y, ${sex}`
  const assumed = unknown.includes('age') || unknown.includes('sex')
  return assumed ? <span className="console__estimated">{text} (assumed: the record is synthetic)</span> : <>{text}</>
}

export default function ExamTab({ snapshot }: { snapshot: Snapshot }) {
  const { patient, protocol, clock, table, scanner } = snapshot
  const timer = clock.contrast_timer_s
  return (
    <div>
      <h3>Patient</h3>
      <dl className="console__facts">
        <Fact label="Name">{patient.name}</Fact>
        <Fact label="Age and sex">
          <AgeAndSex snapshot={snapshot} />
        </Fact>
        <Fact label="Patient height">
          <Estimated snapshot={snapshot} field="height_cm" text={`${patient.height_cm.toFixed(1)} cm`} />
        </Fact>
        <Fact label="Weight">
          <Estimated snapshot={snapshot} field="weight_kg" text={`${patient.weight_kg.toFixed(1)} kg`} />
        </Fact>
      </dl>
      <h3>Exam</h3>
      <dl className="console__facts">
        <Fact label="Protocol">{protocol.title}</Fact>
        <Fact label="Region">{protocol.region}</Fact>
        <Fact label="Source">
          <a href={protocol.source_url} target="_blank" rel="noreferrer">
            Protocol document
          </a>
        </Fact>
      </dl>
      <h3>Clock</h3>
      <dl className="console__facts">
        <Fact label="Simulation time">{formatClock(clock.sim_time_s)}</Fact>
        <Fact label="Speed">x{clock.time_scale}</Fact>
        <Fact label="Contrast timer">{timer == null ? 'Not started' : formatClock(timer)}</Fact>
      </dl>
      <h3>Scanner</h3>
      <dl className="console__facts">
        <Fact label="Model">{scanner.model}</Fact>
        <Fact label="Table height">{Math.round(table.height_mm)} mm</Fact>
        <Fact label="Table position">{table.position_mm == null ? 'No landmark set' : `${Math.round(table.position_mm)} mm from landmark`}</Fact>
        <Fact label="Tube angle">{scanner.tube_angle_deg.toFixed(0)}°</Fact>
        <Fact label="X-ray">
          {scanner.beam_on ? <span className="console__on">ON</span> : 'Off'}
        </Fact>
      </dl>
    </div>
  )
}

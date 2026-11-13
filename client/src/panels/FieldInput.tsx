import { useId, useRef, useState, type ReactElement } from 'react'
import type { FieldView } from '../api/types.gen'
import { useSession } from '../store/session'

const SOURCE_TAG: Record<FieldView['source'], string> = {
  protocol: 'protocol',
  scanner: 'scanner',
  patient: 'patient',
  assumption: 'assumed',
  computed: 'computed',
}

interface Props {
  field: FieldView
  stepId: string
  locked?: boolean
}

type Value = number | boolean | string

function toDraft(value: FieldView['value']): string {
  return value === null || value === undefined ? '' : String(value)
}

/** A number as shown in a field: whole millimetres, one decimal for cm and kg, otherwise at most two. */
export function formatFieldNumber(value: number, unit: string | null | undefined, step?: number | null): string {
  if (!Number.isFinite(value)) return String(value)
  if (unit === 'mm' && (step == null || Number.isInteger(step))) return String(Math.round(value))
  const places = unit === 'cm' || unit === 'kg' ? 1 : 2
  return String(Number(value.toFixed(places)))
}

function parseNumber(draft: string): Value {
  const n = Number(draft)
  return draft.trim() !== '' && Number.isFinite(n) ? n : draft
}

export default function FieldInput({ field, stepId, locked = false }: Props) {
  const send = useSession((s) => s.send)
  const id = useId()
  // The user's typed text, kept only while editing; null means show the server value.
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const disabled = locked || field.editable === false
  const shown = draft ?? (typeof field.value === 'number' ? formatFieldNumber(field.value, field.unit, field.step) : toDraft(field.value))

  // Bumped by every edit and commit; a settling commit acts only if it is still the latest.
  const latest = useRef(0)

  function edit(text: string): void {
    latest.current += 1
    setDraft(text)
    setError(null)
  }

  async function commit(value: Value): Promise<void> {
    latest.current += 1
    const mine = latest.current
    let message: string | null = null
    try {
      const result = await send({ type: 'set_field', step_id: stepId, key: field.key, value })
      if (!result.ok) message = result.error ?? 'The value was not accepted'
    } catch (err) {
      message = err instanceof Error ? err.message : 'The value could not be sent'
    }
    if (latest.current !== mine) return
    setError(message)
    setDraft(null)
  }

  function isUnchanged(text: string): boolean {
    if (field.type !== 'number') return text === toDraft(field.value)
    return text.trim() !== '' && Number(text) === field.value
  }

  function commitDraft(): void {
    if (draft === null) return
    if (isUnchanged(draft)) {
      setDraft(null)
      return
    }
    void commit(field.type === 'number' ? parseNumber(draft) : draft)
  }

  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {field.label}
        <span className="field__tag">{SOURCE_TAG[field.source]}</span>
      </label>
      <span className="field__control">
        {renderControl()}
        {field.unit ? <span className="field__unit">{field.unit}</span> : null}
      </span>
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )

  function renderControl(): ReactElement {
    const common = { id, disabled, title: field.help || undefined }
    if (field.type === 'bool') {
      return <input {...common} type="checkbox" checked={field.value === true} onChange={(e) => void commit(e.target.checked)} />
    }
    if (field.type === 'choice') {
      return (
        <select {...common} value={toDraft(field.value)} onChange={(e) => void commit(e.target.value)}>
          {(field.options ?? []).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )
    }
    if (field.type === 'text') {
      return <input {...common} type="text" value={shown} onChange={(e) => edit(e.target.value)} onBlur={commitDraft} onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} />
    }
    return (
      <input
        {...common}
        type="number"
        value={shown}
        min={field.min ?? undefined}
        max={field.max ?? undefined}
        step={field.step ?? 'any'}
        onChange={(e) => edit(e.target.value)}
        onBlur={commitDraft}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      />
    )
  }
}

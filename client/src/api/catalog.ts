export interface ModalityEntry {
  id: string
  label: string
  available: boolean
}

export interface ProtocolEntry {
  id: string
  title: string
  modality: string
  region: string
  status: string
  source_url: string
}

export interface LabelledEntry {
  id: string
  label: string
}

export interface Catalog {
  modalities: ModalityEntry[]
  protocols: ProtocolEntry[]
  patients: LabelledEntry[]
  scanners: LabelledEntry[]
}

export async function fetchCatalog(): Promise<Catalog> {
  const res = await fetch('/api/catalog')
  if (!res.ok) throw new Error(`Catalog request failed (${res.status})`)
  return (await res.json()) as Catalog
}

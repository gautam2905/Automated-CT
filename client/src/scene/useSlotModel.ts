import { useEffect, useState } from 'react'
import type { Object3D } from 'three'

export type ModelSlot = 'ct_scanner' | 'table' | 'patient' | 'technologist' | 'injector' | 'room'

const MANIFEST_URL = '/models/manifest.json'
const cache = new Map<ModelSlot, Promise<Object3D | null>>()
let manifest: Promise<Record<string, string>> | null = null

function readManifest(): Promise<Record<string, string>> {
  manifest ??= fetch(MANIFEST_URL)
    .then((r) => (r.ok ? (r.json() as Promise<Record<string, unknown>>) : {}))
    .then((raw) => Object.fromEntries(Object.entries(raw).filter(([, v]) => typeof v === 'string')) as Record<string, string>)
    // A missing or unreadable manifest is the normal state until models are added: code-built models are used.
    .catch(() => ({}))
  return manifest
}

async function loadSlot(slot: ModelSlot): Promise<Object3D | null> {
  const file = (await readManifest())[slot]
  if (!file) return null
  try {
    const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js')
    const gltf = await new GLTFLoader().loadAsync(`/models/${file}`)
    return gltf.scene
  } catch {
    // The caller falls back to its code-built model when a listed file cannot be loaded.
    return null
  }
}

/** The downloaded model for a slot named in `public/models/manifest.json`, or null to use the code-built one. */
export function useSlotModel(slot: ModelSlot): Object3D | null {
  const [model, setModel] = useState<Object3D | null>(null)
  useEffect(() => {
    let alive = true
    let pending = cache.get(slot)
    if (!pending) {
      pending = loadSlot(slot)
      cache.set(slot, pending)
    }
    void pending.then((m) => {
      if (alive) setModel(m)
    })
    return () => {
      alive = false
    }
  }, [slot])
  return model
}

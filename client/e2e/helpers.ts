import { expect, type Page } from '@playwright/test'
import type { Snapshot } from '../src/api/types.gen'

/** The URL used by every browser test: `?lowgfx` keeps the software-rendered 3D view from starving the page. */
export const APP_URL = '/?lowgfx'

export type LatestSnapshot = () => Snapshot

/** Keeps the newest snapshot the server sent, so tests can check the engine's own view of the exam. */
export function watchSnapshots(page: Page): LatestSnapshot {
  let latest = ''
  page.on('websocket', (ws) => ws.on('framereceived', (f) => {
    const text = String(f.payload)
    if (text.startsWith('{"type": "snapshot"')) latest = text
  }))
  return () => {
    if (!latest) throw new Error('No snapshot has arrived yet')
    return (JSON.parse(latest) as { data: Snapshot }).data
  }
}

export async function startLiverExam(page: Page, speed = '20'): Promise<void> {
  await page.goto(APP_URL)
  await page.getByLabel('Modality').selectOption('CT')
  await page.getByRole('combobox', { name: /^Exam/ }).selectOption({ label: 'CT Multiphase Liver' })
  await page.getByLabel('Patient').selectOption('sub-000')
  await page.getByRole('button', { name: 'Start exam' }).click()
  await page.getByLabel('Speed').selectOption(speed)
}

/** The status of a step in a snapshot; an unknown id is an error, never "done". */
export function stepStatus(snapshot: Snapshot, id: string): string {
  for (const stage of snapshot.stages) {
    const step = stage.steps.find((s) => s.id === id)
    if (step) return step.status
  }
  throw new Error(`No step called ${id} in the snapshot`)
}

/** Waits until the engine reports a step as done. */
export async function expectStepDone(latest: LatestSnapshot, id: string, timeout = 60_000): Promise<void> {
  await expect.poll(() => stepStatus(latest(), id), { timeout, message: `step ${id} should finish` }).toBe('done')
}

/** Clicks a step's button once it can be clicked, then waits for the engine to report it done. */
export async function performStep(page: Page, latest: LatestSnapshot, id: string, timeout = 60_000): Promise<void> {
  const button = page.locator(`[data-step="${id}"]`).getByRole('button').first()
  await button.click({ timeout })
  await expectStepDone(latest, id, timeout)
  await expect(page.locator(`[data-step="${id}"] [data-status]`)).toHaveAttribute('data-status', 'done')
}

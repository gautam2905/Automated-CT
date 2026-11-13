import { expect, test, type Page } from '@playwright/test'
import type { SeriesPlanView, Snapshot } from '../src/api/types.gen'
import { performStep, startLiverExam, watchSnapshots } from './helpers'

const SCREENS = 'e2e/screens'
const BEFORE_PLANNING = [
  'order_received', 'protocol_assigned', 'chart_check', 'identify_patient', 'safety_screening', 'consent',
  'change_clothes', 'iv_access', 'breath_coaching', 'register_patient', 'load_injector', 'prepare_table',
  'patient_on_table', 'centre_patient', 'connect_injector', 'table_height', 'set_landmark', 'leave_room',
  'topogram_ap', 'topogram_lat', 'check_centring',
]
const ALL = 'noncontrast+arterial+venous+delayed'   // the four series share one range, so they share one box
const DEFAULT_END_MM = 320
const DRAG_UP_PX = 40

const openTab = (page: Page, name: string) => page.locator('.console__tab', { hasText: name }).click()

function plan(snapshot: Snapshot, id = 'noncontrast'): SeriesPlanView {
  const series = snapshot.console.series?.find((s) => s.id === id)
  if (!series) throw new Error(`No ${id} series is planned`)
  return series.plan
}

function fieldValue(snapshot: Snapshot, stepId: string, key: string): unknown {
  const step = snapshot.stages.flatMap((st) => st.steps).find((s) => s.id === stepId)
  return step?.fields?.find((f) => f.key === key)?.value
}

/** Presses on the lower edge of the pending range and lets go `DRAG_UP_PX` higher (toward the head). */
async function dragEndEdgeUp(page: Page): Promise<void> {
  const edge = await page.getByTestId(`handle-${ALL}-end_mm`).boundingBox()
  if (!edge) throw new Error('The end edge of the range has no handle')
  const x = edge.x + edge.width / 2
  const y = edge.y + edge.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x, y - DRAG_UP_PX, { steps: 8 })
  await page.mouse.up()
}

test('a range dragged on the topogram stays drawn, and doing the plan step again applies it to the plan and the dose', async ({ page }) => {
  test.setTimeout(240_000)
  const latest = watchSnapshots(page)
  await startLiverExam(page)
  for (const id of BEFORE_PLANNING) await performStep(page, latest, id, 120_000)
  await openTab(page, 'Images')

  // Before the first plan the pre-filled ranges are already drawn, dashed, and nothing is accepted yet.
  const pending = page.getByTestId(`pending-${ALL}`)
  const accepted = page.getByTestId(`box-${ALL}`)
  await expect(pending).toBeVisible()
  await expect(accepted).toHaveCount(0)
  expect(latest().console.series ?? []).toEqual([])

  await performStep(page, latest, 'plan_ranges')
  const first = plan(latest())
  expect(first.end_mm).toBe(DEFAULT_END_MM)
  await expect(accepted).toBeVisible()
  await expect(pending).toHaveCount(0)              // the fields and the plan agree: one solid box

  await dragEndEdgeUp(page)
  // The drag changed the fields of all four series, and nothing else: the plan and its dose are as before.
  await expect.poll(() => fieldValue(latest(), 'plan_ranges', 'delayed.end_mm')).not.toBe(DEFAULT_END_MM)
  const dragged = fieldValue(latest(), 'plan_ranges', 'noncontrast.end_mm') as number
  expect(dragged).toBeLessThan(DEFAULT_END_MM)
  expect(Number.isInteger(dragged)).toBe(true)
  expect(plan(latest())).toEqual(first)
  // The dragged range does not snap back: it stays as a dashed box beside the accepted one.
  await expect(pending).toBeVisible()
  await expect(accepted).toBeVisible()
  const heights = await Promise.all([pending, accepted].map(async (box) => (await box.boundingBox())?.height ?? 0))
  expect(heights[0]).toBeLessThan(heights[1])
  await expect(page.locator('.topogram svg text', { hasText: 'not accepted yet' })).toBeVisible()
  // Dragging moves the edge and nothing else: it must not select the labels drawn on the image.
  expect(await page.evaluate(() => window.getSelection()?.toString() ?? '')).toBe('')
  await page.screenshot({ path: `${SCREENS}/app3-01-range-dragged-pending.png` })

  // The step is done and can be repeated: "Do again" accepts the dragged range.
  const again = page.locator('[data-step="plan_ranges"]').getByRole('button', { name: 'Do again' })
  await expect(again).toBeEnabled()
  await again.click()
  await expect.poll(() => plan(latest()).end_mm).toBe(dragged)
  const second = plan(latest())
  expect(second.dlp_mgycm).toBeLessThan(first.dlp_mgycm)        // a shorter range, a lower predicted dose
  expect(second.dlp_mgycm).toBeGreaterThan(first.dlp_mgycm / 2)
  expect(plan(latest(), 'delayed').end_mm).toBe(dragged)
  await expect(pending).toHaveCount(0)
  await expect(page.locator('[data-step="confirm_settings"] [data-status]')).toHaveAttribute('data-status', 'ready')

  // The Dose tab shows the new prediction.
  await openTab(page, 'Dose')
  const row = page.locator('.dose-table tbody tr').first()
  await expect(row).toContainText(String(Math.round(second.dlp_mgycm * 10) / 10))
  await expect(page.getByTestId('dose-note')).toContainText('model estimate')
  await page.screenshot({ path: `${SCREENS}/app3-02-range-applied-dose.png` })
})

test('Reset asks first, sits apart from Start, and a second exam with another seed starts clean', async ({ page }) => {
  const latest = watchSnapshots(page)
  await startLiverExam(page)
  await performStep(page, latest, 'order_received', 15_000)
  const firstSession = latest().session_id
  await expect(page.getByRole('button', { name: 'Start exam' })).toBeDisabled()

  await page.getByRole('button', { name: 'Reset' }).click()
  await expect(page.getByText('Discard this exam? It is not saved.')).toBeVisible()
  // The button that throws the exam away is drawn in the alert colour, not like "Start exam".
  const fill = (name: string) => page.getByRole('button', { name }).evaluate((b) => getComputedStyle(b).backgroundColor)
  expect(await fill('Discard exam')).toBe('rgb(166, 55, 49)')
  expect(await fill('Discard exam')).not.toBe(await fill('Start exam'))
  await page.getByRole('button', { name: 'Keep exam' }).click()
  await expect(page.locator('[data-step="order_received"] [data-status]')).toHaveAttribute('data-status', 'done')

  await page.getByRole('button', { name: 'Reset' }).click()
  await page.getByRole('button', { name: 'Discard exam' }).click()
  await expect(page.getByText('Start an exam to see its procedure.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Reset' })).toHaveCount(0)

  await page.getByLabel('Seed').fill('2')
  await page.getByRole('button', { name: 'Start exam' }).click()
  await expect.poll(() => latest().session_id).not.toBe(firstSession)
  const fresh = latest()
  expect(fresh.stages.flatMap((st) => st.steps).filter((s) => s.status === 'done')).toEqual([])
  await expect(page.locator('[data-step="order_received"] [data-status]')).toHaveAttribute('data-status', 'ready')
})

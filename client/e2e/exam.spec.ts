import { expect, test } from '@playwright/test'
import { APP_URL, performStep, startLiverExam, watchSnapshots } from './helpers'

test('an exam can be started and the first steps performed', async ({ page }) => {
  const latest = watchSnapshots(page)
  await startLiverExam(page)
  for (const id of ['order_received', 'protocol_assigned', 'chart_check']) await performStep(page, latest, id, 15000)
  const canvas = page.locator('canvas').first(); await expect(canvas).toBeVisible()
  await page.screenshot({ path: 'e2e/screens/exam-start.png' })
  const px = await canvas.evaluate((c: HTMLCanvasElement) => { const d = document.createElement('canvas'); d.width = 64; d.height = 64
    const g = d.getContext('2d')!; g.drawImage(c, 0, 0, 64, 64); const a = g.getImageData(0, 0, 64, 64).data
    let min = 255, max = 0; for (let i = 0; i < a.length; i += 4) { min = Math.min(min, a[i]); max = Math.max(max, a[i]) } return max - min })
  expect(px).toBeGreaterThan(30)        // the 3D view is not blank
})

test('the steps and the console can be put away and brought back, and the room takes the space', async ({ page }) => {
  const latest = watchSnapshots(page)
  await startLiverExam(page)
  await performStep(page, latest, 'order_received', 15000)
  const roomWidth = async () => (await page.locator('.panel--scene').boundingBox())?.width ?? 0
  const drawnWidth = () => page.locator('.panel--scene canvas').evaluate((c) => c.getBoundingClientRect().width)
  const both = await roomWidth()

  await page.getByRole('button', { name: 'Hide steps' }).click()
  await expect(page.locator('[data-step="order_received"]')).toBeHidden()
  const withoutSteps = await roomWidth()
  expect(withoutSteps).toBeGreaterThan(both + 100)
  await page.getByRole('button', { name: 'Hide console' }).click()
  await expect(page.getByRole('tablist', { name: 'Console' })).toBeHidden()
  const alone = await roomWidth()
  expect(alone).toBeGreaterThan(withoutSteps + 300)
  await expect.poll(drawnWidth).toBeGreaterThan(alone - 40)        // the 3D view is redrawn to fill the wider room
  await page.screenshot({ path: 'e2e/screens/exam-room-alone.png' })

  await page.getByRole('button', { name: 'Show steps' }).click()
  await page.getByRole('button', { name: 'Show console' }).click()
  expect(await roomWidth()).toBeCloseTo(both, 0)
  // Nothing was lost while the sides were away, and the exam goes on.
  await expect(page.locator('[data-step="order_received"] [data-status]')).toHaveAttribute('data-status', 'done')
  await performStep(page, latest, 'protocol_assigned', 15000)
})

test('MRI is listed but not yet available', async ({ page }) => {
  await page.goto(APP_URL); await expect(page.getByLabel('Modality').locator('option', { hasText: 'MRI' })).toBeDisabled()
})

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

test('MRI is listed but not yet available', async ({ page }) => {
  await page.goto(APP_URL); await expect(page.getByLabel('Modality').locator('option', { hasText: 'MRI' })).toBeDisabled()
})

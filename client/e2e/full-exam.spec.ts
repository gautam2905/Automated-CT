import { expect, test, type Page } from '@playwright/test'
import { expectStepDone, performStep, startLiverExam, watchSnapshots, type LatestSnapshot } from './helpers'

const SCREENS = 'e2e/screens'

const ORDER = [
  'order_received', 'protocol_assigned', 'chart_check', 'identify_patient', 'safety_screening', 'consent',
  'change_clothes', 'iv_access', 'breath_coaching', 'register_patient', 'load_injector', 'prepare_table',
  'patient_on_table', 'centre_patient', 'connect_injector', 'table_height', 'set_landmark', 'leave_room',
  'topogram_ap', 'topogram_lat', 'check_centring', 'plan_ranges', 'confirm_settings', 'scan_noncontrast',
  'review_noncontrast', 'monitoring_slice', 'place_roi', 'arm_injector', 'inject_and_arterial',
  'scan_venous', 'scan_delayed', 'review_phases', 'send_images', 'table_out', 'disconnect_injector',
  'patient_off_table', 'post_contrast_care', 'room_turnaround', 'close_exam',
]
const SELF_STARTING = new Set(['scan_venous', 'scan_delayed'])   // they begin by themselves after the injection

type Snapshot = import('../src/api/types.gen').Snapshot

const shot = (page: Page, name: string) => page.screenshot({ path: `${SCREENS}/app2-${name}.png` })
const openTab = (page: Page, name: string) => page.locator('.console__tab', { hasText: name }).click()

const ROI_TOLERANCE_MM = 6   // the click lands on the marker, rounded to whole millimetres

async function placeRegionOnAorta(page: Page, latest: LatestSnapshot): Promise<void> {
  await openTab(page, 'Images')
  const reference = page.getByLabel('Show reference anatomy')
  if (!(await reference.isChecked())) await reference.click()   // the box follows the server, so it flips a moment later
  await expect(reference).toBeChecked()
  await openTab(page, 'Contrast')
  const marker = page.locator('.topogram svg g', { hasText: /aorta/i }).locator('circle')
  await expect(marker).toBeVisible()
  await marker.click()
  // The region fields must now sit on the aorta marker, as the engine reports them.
  await expect
    .poll(() => {
      const snapshot = latest()
      const aorta = snapshot.console.reference_points?.find((p) => p.name === 'aorta')
      const fields = snapshot.stages.flatMap((st) => st.steps).find((st) => st.id === 'place_roi')?.fields ?? []
      const x = fields.find((f) => f.key === 'roi_x_mm')?.value
      const y = fields.find((f) => f.key === 'roi_y_mm')?.value
      if (!aorta || typeof x !== 'number' || typeof y !== 'number') return Infinity
      return Math.hypot(x - aorta.x_mm, y - aorta.y_mm)
    })
    .toBeLessThan(ROI_TOLERANCE_MM)
}

const TOPOGRAM_LENGTH_MM = 512   // the default length of the topogram run

/** True while roughly half of the AP topogram's run has been drawn. */
function halfBuilt(snapshot: Snapshot): boolean {
  const ap = snapshot.console.topograms?.find((t) => t.view === 'AP')
  if (!ap) return false
  const drawnMm = (ap.revealed_to_row - ap.revealed_from_row) * ap.row_mm
  return drawnMm > 0.25 * TOPOGRAM_LENGTH_MM && drawnMm < 0.5 * TOPOGRAM_LENGTH_MM
}

async function shotArterialSlice(page: Page): Promise<void> {
  await openTab(page, 'Images')
  await page.getByRole('tab', { name: 'Arterial' }).click()
  const slice = page.locator('img.viewer__slice')
  await expect(slice).toBeVisible()
  await expect.poll(() => slice.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0)).toBe(true)
  await slice.scrollIntoViewIfNeeded()
  await shot(page, '06-arterial-slice')
}

async function waitForCurve(page: Page): Promise<void> {
  await expect
    .poll(async () => (await page.locator('svg.curve polyline').getAttribute('points'))?.split(' ').length ?? 0, { timeout: 60_000 })
    .toBeGreaterThan(6)
}

async function stepsBeforeExtras(page: Page, latest: LatestSnapshot, id: string): Promise<void> {
  switch (id) {
    case 'review_noncontrast': {
      const answer = page.locator('[data-step="review_noncontrast"] select').first()
      await answer.selectOption('yes')   // the default range covers the liver for this volunteer
      break
    }
    case 'place_roi':
      await placeRegionOnAorta(page, latest)
      break
    case 'topogram_ap': await openTab(page, 'Images'); break
    case 'inject_and_arterial': await openTab(page, 'Contrast'); break
  }
}

async function afterStep(page: Page, id: string): Promise<void> {
  if (id === 'set_landmark') await shot(page, '02-patient-on-table-landmark')
  if (id !== 'plan_ranges') return
  await openTab(page, 'Images')
  await shot(page, '04-planned-ranges')
  await page.getByLabel('Show reference anatomy').click()
  await expect(page.getByLabel('Show reference anatomy')).toBeChecked()
  await expect(page.locator('.topogram svg text', { hasText: 'Top of liver' }).first()).toBeVisible()
  await shot(page, '09-planned-ranges-reference-on')
}

function latest_ap_complete(snapshot: Snapshot): boolean | undefined {
  return snapshot.console.topograms?.find((t) => t.view === 'AP')?.complete
}

const SAMPLE_ROWS = 24   // rows from the top of the acquired band that must already show anatomy
const MIN_GREY_SPREAD = 40

/** Largest grey spread in any of the first revealed rows of the AP canvas, or 0 if nothing was drawn. */
async function apTopogramSpread(page: Page, latest: LatestSnapshot): Promise<number> {
  const ap = latest().console.topograms?.find((t) => t.view === 'AP')
  if (!ap) return 0
  const from = ap.revealed_from_row
  return page.locator('canvas[aria-label="AP topogram"]').evaluate((c: HTMLCanvasElement, [row, count]: number[]) => {
    const data = c.getContext('2d')!.getImageData(0, row, c.width, count).data
    let lo = 255
    let hi = 0
    for (let i = 0; i < data.length; i += 4) {
      lo = Math.min(lo, data[i])
      hi = Math.max(hi, data[i])
    }
    return hi - lo
  }, [from, SAMPLE_ROWS])
}

test('a whole CT liver exam can be performed through the interface', async ({ page }) => {
  test.setTimeout(300_000)
  const lastSnapshot = watchSnapshots(page)
  await startLiverExam(page)
  await shot(page, '01-just-started')

  for (const id of ORDER) {
    if (SELF_STARTING.has(id)) {
      await expectStepDone(lastSnapshot, id, 120_000)
      if (id === 'scan_venous') await shotArterialSlice(page)
      continue
    }
    await stepsBeforeExtras(page, lastSnapshot, id)
    if (id === 'topogram_ap') {
      await page.getByLabel('Speed').selectOption('1')   // slow enough to catch the image half built
      // The software-drawn 3D view makes the page too slow to catch the scan half way, so hide it for this shot.
      const hide3d = await page.addStyleTag({ content: '.panel--scene canvas { visibility: hidden }' })
      await page.locator(`[data-step="${id}"]`).getByRole('button').first().click()
      await expect.poll(() => halfBuilt(lastSnapshot()), { timeout: 60_000, intervals: [100] }).toBe(true)
      // Rows already revealed must show anatomy while the scan is still running, not black.
      await expect.poll(() => apTopogramSpread(page, lastSnapshot), { timeout: 20_000 }).toBeGreaterThan(MIN_GREY_SPREAD)
      await shot(page, '03-ap-topogram-building')
      expect(latest_ap_complete(lastSnapshot())).toBe(false)
      await hide3d.evaluate((el) => el.remove())
      await expectStepDone(lastSnapshot, id)
      await page.getByLabel('Speed').selectOption('20')
    } else if (id === 'inject_and_arterial') {
      await page.locator(`[data-step="${id}"]`).getByRole('button').first().click()
      await waitForCurve(page)
      await shot(page, '05-contrast-monitoring')
      await expectStepDone(lastSnapshot, id, 120_000)
    } else {
      await performStep(page, lastSnapshot, id, 120_000)
    }
    await afterStep(page, id)
  }

  await openTab(page, 'Dose')
  await page.waitForTimeout(3000)   // the low-graphics 3D view redraws every two seconds
  await shot(page, '07-dose')
  await page.screenshot({ path: `${SCREENS}/app2-08-whole-page-end.png`, fullPage: true })

  const end = lastSnapshot()
  expect(end.console.series.map((x) => x.status)).toEqual(['done', 'done', 'done', 'done'])
  expect(end.console.tracking?.state).toBe('triggered')
  expect(end.pose.stage).toBe('away')
  expect(end.stages.at(-1)?.steps.at(-1)).toMatchObject({ id: 'close_exam', status: 'done' })
  await openTab(page, 'Contrast')
  await expect(page.getByRole('heading', { name: /Bolus tracking, triggered/ })).toBeVisible()
})

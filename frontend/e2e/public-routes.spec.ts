import AxeBuilder from "@axe-core/playwright"
import { expect, test } from "@playwright/test"

const publicRoutes = [
  { path: "/", heading: /turn rough product ideas/i, allowsSessionProbeFailure: true },
  { path: "/legal/terms", heading: /terms/i },
  { path: "/legal/privacy", heading: /privacy/i },
  { path: "/legal/retention", heading: /retention/i },
]

for (const route of publicRoutes) {
  test(`${route.path} renders without serious accessibility violations`, async ({ page }) => {
    const consoleErrors: string[] = []
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text())
    })

    await page.route("**/retention/policy", (request) =>
      request.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          policy_version: "trash-v1",
          trash_days: 30,
          legacy_archived_days: 180,
          stage_versions_keep: 20,
          stage_versions_min_age_days: 90,
          storyboards_keep: 5,
          storyboards_min_age_days: 90,
          cost_events_days: 180,
          eval_results_days: 180,
        }),
      }),
    )
    await page.goto(route.path)
    await expect(page.getByRole("heading", { name: route.heading }).first()).toBeVisible()
    const results = await new AxeBuilder({ page }).analyze()
    expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))).toEqual([])
    if (!route.allowsSessionProbeFailure) {
      expect(consoleErrors).toEqual([])
    }
  })
}

test("landing remains usable at 200% zoom and mobile width", async ({ page }) => {
  await page.goto("/")
  await page.evaluate(() => { document.documentElement.style.zoom = "2" })
  await expect(page.getByRole("button", { name: /sign in with google/i })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(overflow).toBe(false)
})

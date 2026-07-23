import { expect, test } from "@playwright/test"

test("new user can create a workspace and see the locked stage pipeline", async ({ page }) => {
  await page.goto("/")

  await expect(page.getByRole("heading", { name: /thought2build/i })).toBeVisible()
  await page.getByRole("button", { name: /sign in with google/i }).click()

  await page.goto("/dashboard")
  await expect(page.getByText(/50 credits/i)).toBeVisible()
  await page.getByRole("button", { name: /create workspace/i }).click()
  await page.getByLabel(/workspace name/i).fill("Harness smoke project")
  await page.getByLabel(/problem statement/i).fill(
    "Build a small project planning application that turns a user problem statement into specification, plan, harness, and tasks with quality checks.",
  )
  await page.getByRole("button", { name: /openai/i }).click()
  await expect(page.getByLabel(/model/i)).toHaveCount(0)
  await page.getByRole("button", { name: /^create$/i }).click()

  await expect(page.getByRole("button", { name: /spec/i })).toBeEnabled()
  await expect(page.getByRole("button", { name: /plan/i })).toBeDisabled()
  await expect(page.getByRole("button", { name: /harness/i })).toBeDisabled()
  await expect(page.getByRole("button", { name: /tasks/i })).toBeDisabled()
})

test("pipeline exposes generation, finalise, staleness, and export controls", async ({ page }) => {
  await page.goto("/workspace/test-workspace")

  await page.getByRole("button", { name: /generate/i }).click()
  await expect(page.getByText(/10 credits/i)).toBeVisible()
  await page.getByRole("button", { name: /confirm/i }).click()
  await expect(page.getByText(/quality/i)).toBeVisible({ timeout: 15000 })

  await page.getByRole("button", { name: /finalise/i }).click()
  await expect(page.getByRole("button", { name: /plan/i })).toBeEnabled()
  await expect(page.getByText(/review/i)).toBeVisible()

  await expect(page.getByRole("button", { name: /export/i })).toBeDisabled()
})

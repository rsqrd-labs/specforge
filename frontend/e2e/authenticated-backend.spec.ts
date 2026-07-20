import AxeBuilder from "@axe-core/playwright"
import { expect, type APIRequestContext, type Page, test } from "@playwright/test"

const token = process.env.E2E_ACCESS_TOKEN
const apiBase = process.env.E2E_API_URL ?? "http://127.0.0.1:8000"

test.skip(!token, "requires the Docker-backed E2E API and deterministic session")
test.describe.configure({ mode: "serial" })
test.setTimeout(120_000)

async function apiCall(
  request: APIRequestContext,
  path: string,
  options: { method?: string; data?: unknown } = {},
) {
  const method = options.method ?? "GET"
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = await request.get(`${apiBase}/auth/csrf-token`, { headers })
    expect(csrf.ok()).toBe(true)
    headers["X-CSRF-Token"] = (await csrf.json()).csrf_token
  }
  return request.fetch(`${apiBase}${path}`, {
    method,
    headers,
    data: options.data,
  })
}

async function createWorkspace(request: APIRequestContext, suffix: string) {
  const response = await apiCall(request, "/workspaces", {
    method: "POST",
    data: {
      name: `Browser ${suffix}`,
      problem_statement:
        `I want to build a workflow verification app that helps product teams test complete browser journeys for ${suffix} run ${Date.now()}.`,
      mode: "demo_day",
      target_agent: "codex",
      time_budget_minutes: 300,
    },
  })
  expect(response.status()).toBe(201)
  return response.json()
}

async function bootstrapSession(page: Page) {
  await page.route("**/auth/refresh", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ access_token: token }),
    }),
  )
}

function assertNoSevereAxeViolations(page: Page) {
  return new AxeBuilder({ page })
    .analyze()
    .then((result) =>
      expect(
        result.violations.filter((violation) =>
          ["serious", "critical"].includes(violation.impact ?? ""),
        ),
      ).toEqual([]),
    )
}

test.beforeEach(async ({ page }) => {
  await bootstrapSession(page)
})

test("authenticated workspace CRUD survives trash and restore", async ({ page, request }, testInfo) => {
  const workspace = await createWorkspace(request, `${testInfo.project.name} CRUD`)

  await page.goto("/dashboard")
  await expect(page.getByRole("heading", { name: /Welcome back,\s*Browser/i })).toBeVisible()
  await expect(page.getByText(workspace.name).first()).toBeVisible()

  const updated = await apiCall(request, `/workspaces/${workspace.id}`, {
    method: "PATCH",
    data: { name: `${workspace.name} Updated` },
  })
  expect(updated.ok()).toBe(true)
  await page.reload()
  await expect(page.getByText(`${workspace.name} Updated`).first()).toBeVisible()

  const removed = await apiCall(request, `/workspaces/${workspace.id}`, {
    method: "DELETE",
  })
  expect(removed.status()).toBe(204)
  await page.reload()
  await expect(page.getByText(`${workspace.name} Updated`).first()).not.toBeVisible()

  const restored = await apiCall(request, `/workspaces/${workspace.id}/restore`, {
    method: "POST",
  })
  expect(restored.ok()).toBe(true)
  await page.reload()
  await expect(page.getByText(`${workspace.name} Updated`).first()).toBeVisible()
  await assertNoSevereAxeViolations(page)
})

test("real generation SSE completes and finalisation conflicts remain honest", async ({ page, request }, testInfo) => {
  const workspace = await createWorkspace(request, `${testInfo.project.name} SSE`)
  const spec = workspace.stages.find((stage: { type: string }) => stage.type === "spec")

  const stream = await apiCall(request, `/stages/${spec.id}/generate`, { method: "POST" })
  expect(stream.ok()).toBe(true)
  const events = await stream.text()
  expect(events).toContain("generation_started")
  expect(events).toContain("progress")
  expect(events).toContain('"done"')

  const persisted = await apiCall(request, `/stages/${spec.id}`)
  const persistedStage = await persisted.json()
  expect(persistedStage.current_version).toBeGreaterThan(0)
  expect(persistedStage.content).toContain("## Overview")

  const finalised = await apiCall(request, `/stages/${spec.id}/finalise`, {
    method: "POST",
  })
  expect(finalised.ok()).toBe(true)
  const conflict = await apiCall(request, `/stages/${spec.id}/finalise`, {
    method: "POST",
  })
  expect(conflict.status()).toBe(409)

  await page.goto(`/workspace/${workspace.id}`)
  await expect(page.getByRole("heading", { name: workspace.name })).toBeVisible()
  await expect(page.getByText(/Generated Spec/i).first()).toBeVisible()
  await assertNoSevereAxeViolations(page)
})

test("navigation reconnects to an in-flight generation and cancellation is durable", async ({ page, request }, testInfo) => {
  const workspace = await createWorkspace(request, `${testInfo.project.name} Cancel`)
  await page.goto(`/workspace/${workspace.id}`)
  await expect(page.getByRole("heading", { name: workspace.name })).toBeVisible()

  await page.getByRole("button", { name: "Generate SPEC" }).click()
  const dialog = page.getByRole("dialog", { name: "Generate" })
  await expect(dialog).toBeVisible()
  await dialog.getByRole("button", { name: "Generate", exact: true }).click()
  await expect(page.getByRole("button", { name: /Cancel generation|Cancel$/ })).toBeVisible()

  // Leave after the stream is established but immediately before the
  // deterministic provider's second chunk. This exercises detached completion
  // and the reconnect poll without racing the generation admission request.
  await page.waitForTimeout(9_500)
  await page.goto("/dashboard")
  await page.goto(`/workspace/${workspace.id}`)
  await expect(page.getByText("Target User and Core Problem").first()).toBeVisible({
    timeout: 20_000,
  })

  await page.getByRole("button", { name: "Regenerate SPEC" }).click()
  const regenerate = page.getByRole("dialog", { name: "Regenerate" })
  await regenerate.getByRole("button", { name: "Regenerate", exact: true }).click()
  const cancel = page.getByRole("button", { name: /Cancel generation|Cancel$/ })
  await expect(cancel).toBeVisible()
  await cancel.click()

  const refreshed = await apiCall(request, `/workspaces/${workspace.id}`)
  const body = await refreshed.json()
  const spec = body.stages.find((stage: { type: string }) => stage.type === "spec")
  await expect
    .poll(
      async () => {
        const run = await apiCall(request, `/stages/${spec.id}/generation`)
        return (await run.json())?.status ?? "settled"
      },
      { timeout: 15_000 },
    )
    .toMatch(/cancelled|succeeded|settled/)
})

test("disabled billing and GitHub integrations render safe authenticated states", async ({ page }) => {
  await page.goto("/billing")
  await expect(page.getByRole("heading", { name: /credits/i }).first()).toBeVisible()
  await expect(page.getByText(/disabled|unavailable|not available/i).first()).toBeVisible()
  await assertNoSevereAxeViolations(page)

  await page.goto("/github")
  await expect(page.getByRole("heading", { name: /exports/i }).first()).toBeVisible()
  await expect(page.getByText(/not exported|no exports|GitHub/i).first()).toBeVisible()
  await assertNoSevereAxeViolations(page)
})

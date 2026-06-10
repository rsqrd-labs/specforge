import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { IncrementTimeline } from "./IncrementTimeline"
import {
  createIdea,
  createIncrement,
  listIdeas,
  listIncrements,
  pushIncrement,
} from "../../services/api"
import type { Increment, IncrementIdea } from "../../types/github"

vi.mock("../../services/api", () => ({
  listIncrements: vi.fn(),
  listIdeas: vi.fn(),
  createIncrement: vi.fn(),
  createIdea: vi.fn(),
  pushIncrement: vi.fn(),
  getApiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const mockListIncrements = vi.mocked(listIncrements)
const mockListIdeas = vi.mocked(listIdeas)
const mockCreate = vi.mocked(createIncrement)
const mockCreateIdea = vi.mocked(createIdea)
const mockPush = vi.mocked(pushIncrement)

function inc(overrides: Partial<Increment> = {}): Increment {
  return {
    id: "inc-1",
    sequence: 1,
    title: "Add billing",
    status: "ready",
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    ...overrides,
  }
}

function idea(overrides: Partial<IncrementIdea> = {}): IncrementIdea {
  return {
    id: "idea-1",
    source: "user",
    external_ref: null,
    status: "open",
    text: "Dark mode toggle",
    increment_id: null,
    created_at: "2026-06-02T00:00:00Z",
    ...overrides,
  }
}

function renderTimeline(props: Partial<Parameters<typeof IncrementTimeline>[0]> = {}) {
  return render(
    <IncrementTimeline
      workspaceId="ws-1"
      enabled
      hasBaselinePush
      {...props}
    />,
  )
}

afterEach(() => vi.clearAllMocks())

describe("IncrementTimeline", () => {
  it("renders the increments newest-first with the v1 baseline anchoring the spine", async () => {
    mockListIncrements.mockResolvedValue([
      inc({ id: "inc-2", sequence: 2, title: "Add teams", status: "pushed" }),
      inc({ id: "inc-1", sequence: 1, title: "Add billing", status: "ready" }),
    ])
    mockListIdeas.mockResolvedValue([])

    renderTimeline()

    const list = await screen.findByRole("list")
    const items = within(list).getAllByRole("listitem")
    // newest increment first, baseline last
    expect(items[0]).toHaveTextContent("Add teams")
    expect(items[1]).toHaveTextContent("Add billing")
    expect(items[items.length - 1]).toHaveTextContent("v1")
    expect(items[items.length - 1]).toHaveTextContent(/baseline/i)
  })

  it("generates an increment from a feature request (additive) and refreshes", async () => {
    mockListIncrements
      .mockResolvedValueOnce([])
      .mockResolvedValue([inc({ title: "Add billing", status: "ready" })])
    mockListIdeas.mockResolvedValue([])
    mockCreate.mockResolvedValue({
      ...inc(),
      new_task_count: 3,
    })

    renderTimeline()

    const input = await screen.findByLabelText(/describe the next increment/i)
    fireEvent.change(input, {
      target: { value: "Add a billing page with Stripe checkout" },
    })
    fireEvent.click(screen.getByRole("button", { name: /add increment/i }))

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith("ws-1", {
        feature_request: "Add a billing page with Stripe checkout",
        mode: "additive",
      }),
    )
    // the refetched increment appears on the rail
    expect(await screen.findByText("Add billing")).toBeInTheDocument()
  })

  it("blocks a too-short feature request with a calm hint (no request)", async () => {
    mockListIncrements.mockResolvedValue([])
    mockListIdeas.mockResolvedValue([])

    renderTimeline()

    const input = await screen.findByLabelText(/describe the next increment/i)
    fireEvent.change(input, { target: { value: "tiny" } })
    fireEvent.click(screen.getByRole("button", { name: /add increment/i }))

    expect(screen.getByRole("alert")).toHaveTextContent(/at least 8 characters/i)
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it("maps an out-of-credits 402 to a clear message", async () => {
    mockListIncrements.mockResolvedValue([])
    mockListIdeas.mockResolvedValue([])
    mockCreate.mockRejectedValue({ response: { status: 402 } })

    renderTimeline()

    const input = await screen.findByLabelText(/describe the next increment/i)
    fireEvent.change(input, { target: { value: "Add an admin dashboard" } })
    fireEvent.click(screen.getByRole("button", { name: /add increment/i }))

    expect(await screen.findByText(/out of credits/i)).toBeInTheDocument()
  })

  it("pushes a ready increment to GitHub when a baseline push exists", async () => {
    mockListIncrements.mockResolvedValue([inc({ status: "ready" })])
    mockListIdeas.mockResolvedValue([])
    mockPush.mockResolvedValue({ increment_id: "inc-1", status: "generating" })

    renderTimeline({ hasBaselinePush: true })

    fireEvent.click(await screen.findByRole("button", { name: /push increment 1 to github/i }))

    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("ws-1", "inc-1"),
    )
  })

  it("hides the push action when there is no baseline push yet", async () => {
    mockListIncrements.mockResolvedValue([inc({ status: "ready" })])
    mockListIdeas.mockResolvedValue([])

    renderTimeline({ hasBaselinePush: false })

    await screen.findByText("Add billing")
    expect(
      screen.queryByRole("button", { name: /push increment 1 to github/i }),
    ).not.toBeInTheDocument()
  })

  it("promote prefills the compose input rather than mutating the idea", async () => {
    mockListIncrements.mockResolvedValue([])
    mockListIdeas.mockResolvedValue([idea({ text: "Webhook retries" })])

    renderTimeline()

    fireEvent.click(await screen.findByRole("button", { name: /promote/i }))

    const input = screen.getByLabelText(/describe the next increment/i)
    expect(input).toHaveValue("Webhook retries")
    // it composes, it does not silently create an increment
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it("captures a new idea into the backlog", async () => {
    mockListIncrements.mockResolvedValue([])
    mockListIdeas.mockResolvedValue([])
    mockCreateIdea.mockResolvedValue(idea())

    renderTimeline()

    const input = await screen.findByLabelText(/capture an idea/i)
    fireEvent.change(input, { target: { value: "Add SSO" } })
    fireEvent.click(screen.getByRole("button", { name: /add idea/i }))

    await waitFor(() =>
      expect(mockCreateIdea).toHaveBeenCalledWith("ws-1", { text: "Add SSO" }),
    )
  })
})

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
    expect(items[items.length - 1]).toHaveTextContent("Version 1")
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

    const input = await screen.findByLabelText(/what should change in the next version/i)
    fireEvent.change(input, {
      target: { value: "Add a billing page with Stripe checkout" },
    })
    fireEvent.click(screen.getByRole("button", { name: /generate version 2/i }))

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith("ws-1", {
        feature_request: "Add a billing page with Stripe checkout",
        mode: "additive",
      }),
    )
    // the refetched increment appears on the rail
    expect(await screen.findByText("Add billing")).toBeInTheDocument()
  })

  it("explains a too-short request and keeps generation unavailable", async () => {
    mockListIncrements.mockResolvedValue([])
    mockListIdeas.mockResolvedValue([])

    renderTimeline()

    const input = await screen.findByLabelText(/what should change in the next version/i)
    fireEvent.change(input, { target: { value: "tiny" } })
    const generate = screen.getByRole("button", { name: /generate version 2/i })
    expect(generate).toBeDisabled()
    expect(screen.getByText(/at least 4 words and 20 characters/i)).toBeInTheDocument()
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it("maps an out-of-credits 402 to a clear message", async () => {
    mockListIncrements.mockResolvedValue([])
    mockListIdeas.mockResolvedValue([])
    mockCreate.mockRejectedValue({ response: { status: 402 } })

    renderTimeline()

    const input = await screen.findByLabelText(/what should change in the next version/i)
    fireEvent.change(input, { target: { value: "Add an admin dashboard" } })
    fireEvent.click(screen.getByRole("button", { name: /generate version 2/i }))

    expect(await screen.findByText(/out of credits/i)).toBeInTheDocument()
  })

  it("shows truthful elapsed generation guidance instead of simulated stages", async () => {
    mockListIncrements.mockResolvedValue([])
    mockListIdeas.mockResolvedValue([])
    mockCreate.mockImplementation(() => new Promise(() => {}))

    renderTimeline()

    const input = await screen.findByLabelText(/what should change in the next version/i)
    fireEvent.change(input, {
      target: { value: "Add team invitations for administrators" },
    })
    fireEvent.click(screen.getByRole("button", { name: /generate version 2/i }))

    expect(await screen.findByText(/building a task-only delta/i)).toBeInTheDocument()
    expect(screen.getByText(/usually takes 1–2 minutes/i)).toBeInTheDocument()
    expect(screen.queryByText(/reading your baseline/i)).not.toBeInTheDocument()
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

  it("pauses increment create, push, capture, and promote actions while locked", async () => {
    mockListIncrements.mockResolvedValue([inc({ status: "ready" })])
    mockListIdeas.mockResolvedValue([
      idea({ text: "Add automatic webhook retry handling" }),
    ])

    renderTimeline({
      hasBaselinePush: true,
      disabled: true,
      disabledReason: "Editing resumes when generation finishes.",
    })

    const incrementInput = await screen.findByLabelText(/what should change in the next version/i)
    expect(incrementInput).toBeDisabled()
    expect(screen.getByRole("button", { name: /generate version 3/i })).toBeDisabled()

    const push = await screen.findByRole("button", { name: /push increment 1 to github/i })
    expect(push).toBeDisabled()
    expect(push).toHaveAccessibleDescription(
      /editing resumes when generation finishes/i,
    )

    const ideaInput = screen.getByLabelText(/capture an idea/i)
    expect(ideaInput).toBeDisabled()
    expect(screen.getByRole("button", { name: /save idea/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /use idea for next version/i })).toBeDisabled()

    fireEvent.click(push)
    fireEvent.click(screen.getByRole("button", { name: /use idea for next version/i }))
    expect(mockPush).not.toHaveBeenCalled()
    expect(mockCreate).not.toHaveBeenCalled()
    expect(mockCreateIdea).not.toHaveBeenCalled()
  })

  it("hides the push action when there is no baseline push yet", async () => {
    mockListIncrements.mockResolvedValue([inc({ status: "ready" })])
    mockListIdeas.mockResolvedValue([])

    renderTimeline({ hasBaselinePush: false })

    await screen.findByText("Add billing")
    expect(
      screen.queryByRole("button", { name: /push increment 1 to github/i }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/export version 1 first/i)).toBeInTheDocument()
  })

  it("uses a saved idea as the source of the next version", async () => {
    mockListIncrements.mockResolvedValue([])
    mockListIdeas.mockResolvedValue([
      idea({ text: "Add automatic webhook retry handling" }),
    ])

    renderTimeline()

    fireEvent.click(await screen.findByRole("button", { name: /use idea/i }))

    const input = screen.getByLabelText(/what should change in the next version/i)
    expect(input).toHaveValue("Add automatic webhook retry handling")
    fireEvent.click(screen.getByRole("button", { name: /generate version 2/i }))
    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith("ws-1", {
        feature_request: "Add automatic webhook retry handling",
        mode: "additive",
        idea_id: "idea-1",
      }),
    )
  })

  it("captures a new idea into the backlog", async () => {
    mockListIncrements.mockResolvedValue([])
    mockListIdeas.mockResolvedValue([])
    mockCreateIdea.mockResolvedValue(idea())

    renderTimeline()

    const input = await screen.findByLabelText(/capture an idea/i)
    fireEvent.change(input, { target: { value: "Add SSO" } })
    fireEvent.click(screen.getByRole("button", { name: /save idea/i }))

    await waitFor(() =>
      expect(mockCreateIdea).toHaveBeenCalledWith("ws-1", { text: "Add SSO" }),
    )
  })

  it("shows a retryable error instead of disguising a failed load as an empty timeline", async () => {
    mockListIncrements.mockRejectedValue(new Error("offline"))
    mockListIdeas.mockResolvedValue([])

    renderTimeline()

    expect(await screen.findByText(/versions could not be loaded/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument()
  })

  it("labels the next generated version after the newest persisted sequence", async () => {
    mockListIncrements.mockResolvedValue([
      inc({ id: "inc-2", sequence: 2, title: "Add teams" }),
      inc({ id: "inc-1", sequence: 1, title: "Add billing" }),
    ])
    mockListIdeas.mockResolvedValue([])

    renderTimeline()

    expect(await screen.findByText("Creates Version 4")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /generate version 4/i })).toBeInTheDocument()
  })
})

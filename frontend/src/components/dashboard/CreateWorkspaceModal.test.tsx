import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { CreateWorkspaceModal } from "./CreateWorkspaceModal"

// Mutable flag state so each test can flip the build-time gate. vi.hoisted keeps
// it available to the hoisted vi.mock factory below.
const { flagState } = vi.hoisted(() => ({
  flagState: { brandedLoaders: true, demoDayMode: false },
}))

vi.mock("../../config/featureFlags", () => ({ featureFlags: flagState }))

const createWorkspaceMock = vi.fn()
vi.mock("../../store/workspaceStore", () => ({
  useWorkspaceStore: () => ({ createWorkspace: createWorkspaceMock }),
}))

const navigateMock = vi.fn()
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock("../../services/api", () => ({
  getProviders: vi.fn().mockResolvedValue({
    providers: [
      {
        id: "openai",
        name: "OpenAI",
        selectable: true,
        configured: true,
        health: "healthy",
        message: "",
      },
    ],
  }),
  getApiErrorMessage: (_error: unknown, fallback: string) => fallback,
}))

const VALID_STATEMENT =
  "Build a small task tracker where a user can add, complete, and list todos."

function renderModal() {
  return render(
    <MemoryRouter>
      <CreateWorkspaceModal onClose={vi.fn()} balance={100} generationCost={10} />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  flagState.demoDayMode = false
  createWorkspaceMock.mockReset()
  createWorkspaceMock.mockResolvedValue({ id: "ws-1" })
  navigateMock.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("CreateWorkspaceModal — Demo Day mode", () => {
  it("hides the Mode selector entirely when the build flag is off", () => {
    renderModal()
    expect(screen.queryByText("Demo Day")).not.toBeInTheDocument()
    expect(screen.getByText(/Coding agent instructions/)).toBeInTheDocument()
    // Standard pipeline preview is unchanged (no handoff step).
    expect(screen.queryByText(/Build-ready handoff/)).not.toBeInTheDocument()
  })

  it("sends the selected agent for a standard create", async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText("Idea Name"), "Todos")
    await user.type(screen.getByLabelText("What should this become?"), VALID_STATEMENT)
    await user.click(screen.getByRole("button", { name: /Generate/ }))

    await waitFor(() => expect(createWorkspaceMock).toHaveBeenCalledOnce())
    const payload = createWorkspaceMock.mock.calls[0][0]
    expect(payload).not.toHaveProperty("mode")
    expect(payload.target_agent).toBe("claude_code")
  })

  it("reveals the Mode selector when the flag is on", () => {
    flagState.demoDayMode = true
    renderModal()
    expect(screen.getByText("Standard")).toBeInTheDocument()
    expect(screen.getByText("Demo Day")).toBeInTheDocument()
    expect(screen.getByText(/Coding agent instructions/)).toBeInTheDocument()
  })

  it("reveals the target-agent picker and handoff preview when Demo Day is chosen", async () => {
    flagState.demoDayMode = true
    const user = userEvent.setup()
    renderModal()

    await user.click(screen.getByRole("button", { name: /Demo Day/ }))
    expect(screen.getByText(/Coding agent/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Claude Code/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Codex/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Both/ })).toBeInTheDocument()
    // The pipeline preview gains the handoff step (exact text — distinct from the
    // longer mode-option description).
    expect(screen.getByText("Build-ready handoff")).toBeInTheDocument()
  })

  it("threads mode + the chosen agent into the create payload", async () => {
    flagState.demoDayMode = true
    const user = userEvent.setup()
    renderModal()

    await user.type(screen.getByLabelText("Idea Name"), "Todos")
    await user.type(screen.getByLabelText("What should this become?"), VALID_STATEMENT)
    await user.click(screen.getByRole("button", { name: /Demo Day/ }))
    await user.click(screen.getByRole("button", { name: /Codex/ }))
    await user.click(screen.getByRole("button", { name: /^Generate/ }))

    await waitFor(() => expect(createWorkspaceMock).toHaveBeenCalledOnce())
    const payload = createWorkspaceMock.mock.calls[0][0]
    expect(payload.mode).toBe("demo_day")
    expect(payload.target_agent).toBe("codex")
  })
})

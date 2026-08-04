import { fireEvent, render, screen, waitFor } from "@testing-library/react"
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
  it("validates required fields and clears errors as the user repairs them", async () => {
    const user = userEvent.setup()
    renderModal()
    await user.click(screen.getByRole("button", { name: /generate workspace spec/i }))
    expect(screen.getByText("Name is required")).toBeInTheDocument()
    expect(screen.getByText(/at least 50 characters/i)).toBeInTheDocument()
    await user.type(screen.getByLabelText("Idea Name"), "Fixed")
    await user.type(screen.getByLabelText("What should this become?"), VALID_STATEMENT)
    expect(screen.queryByText("Name is required")).not.toBeInTheDocument()
    expect(screen.queryByText(/at least 50 characters/i)).not.toBeInTheDocument()
  })

  it("uses quick starts and clears explicit template provenance", async () => {
    const template = {
      id: "tpl", slug: "auth", name: "Auth starter", description: "desc", category: "auth" as const,
      problem_statement: VALID_STATEMENT, sort_order: 1, active: true, created_at: "",
    }
    const { unmount } = render(
      <MemoryRouter><CreateWorkspaceModal onClose={vi.fn()} initialName="Auth" initialStatement={VALID_STATEMENT} initialTemplate={template} balance={null} generationCost={10} /></MemoryRouter>,
    )
    expect(screen.getByText("Auth starter")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "clear" }))
    expect(screen.getByLabelText("Idea Name")).toHaveValue("")
    expect(screen.queryByText("Auth starter")).not.toBeInTheDocument()
    unmount()
    renderModal()
    const quickStart = screen.getAllByRole("button").find((button) => button.classList.contains("modal-template-chip"))!
    fireEvent.click(quickStart)
    expect(screen.getByLabelText("Idea Name")).not.toHaveValue("")
  })

  it("preserves form data and surfaces a retryable create failure", async () => {
    createWorkspaceMock.mockRejectedValue(new Error("offline"))
    renderModal()
    await userEvent.type(screen.getByLabelText("Idea Name"), "Todos")
    await userEvent.type(screen.getByLabelText("What should this become?"), VALID_STATEMENT)
    await userEvent.click(screen.getByRole("button", { name: /generate workspace spec/i }))
    expect(await screen.findByText("Workspace could not be created")).toBeInTheDocument()
    expect(screen.getByLabelText("Idea Name")).toHaveValue("Todos")
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
    expect(screen.queryByText("Workspace could not be created")).not.toBeInTheDocument()
  })

  it("closes from the backdrop and forwards outside wheel movement into the form", () => {
    const close = vi.fn()
    const { container } = render(<MemoryRouter><CreateWorkspaceModal onClose={close} balance={5} generationCost={10} /></MemoryRouter>)
    expect(screen.getByText(/only 5 left/i)).toBeInTheDocument()
    const backdrop = container.querySelector(".create-modal-backdrop") as HTMLElement
    const form = container.querySelector("form") as HTMLFormElement
    fireEvent.wheel(backdrop, { deltaY: 80 })
    expect(form.scrollTop).toBe(80)
    fireEvent.click(backdrop)
    expect(close).toHaveBeenCalled()
  })

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

  it("defaults the time budget to 5h and restricted environment to false", async () => {
    flagState.demoDayMode = true
    const user = userEvent.setup()
    renderModal()

    await user.type(screen.getByLabelText("Idea Name"), "Todos")
    await user.type(screen.getByLabelText("What should this become?"), VALID_STATEMENT)
    await user.click(screen.getByRole("button", { name: /Demo Day/ }))
    expect(screen.getByRole("button", { name: "5h" })).toHaveAttribute(
      "aria-pressed",
      "true",
    )
    await user.click(screen.getByRole("button", { name: /^Generate/ }))

    await waitFor(() => expect(createWorkspaceMock).toHaveBeenCalledOnce())
    const payload = createWorkspaceMock.mock.calls[0][0]
    expect(payload.time_budget_minutes).toBe(300)
    expect(payload.restricted_environment).toBe(false)
  })

  it("threads a chosen time budget and restricted-environment flag into the payload", async () => {
    flagState.demoDayMode = true
    const user = userEvent.setup()
    renderModal()

    await user.type(screen.getByLabelText("Idea Name"), "Todos")
    await user.type(screen.getByLabelText("What should this become?"), VALID_STATEMENT)
    await user.click(screen.getByRole("button", { name: /Demo Day/ }))
    await user.click(screen.getByRole("button", { name: "24h" }))
    await user.click(screen.getByRole("switch", { name: /Locked-down environment/ }))
    await user.click(screen.getByRole("button", { name: /^Generate/ }))

    await waitFor(() => expect(createWorkspaceMock).toHaveBeenCalledOnce())
    const payload = createWorkspaceMock.mock.calls[0][0]
    expect(payload.time_budget_minutes).toBe(1440)
    expect(payload.restricted_environment).toBe(true)
  })

  it("omits time budget and restricted environment for a standard create", async () => {
    flagState.demoDayMode = true
    const user = userEvent.setup()
    renderModal()

    await user.type(screen.getByLabelText("Idea Name"), "Todos")
    await user.type(screen.getByLabelText("What should this become?"), VALID_STATEMENT)
    // Mode defaults to "standard" — the Demo Day-only controls never render.
    expect(screen.queryByText("Build time budget")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /^Generate/ }))

    await waitFor(() => expect(createWorkspaceMock).toHaveBeenCalledOnce())
    const payload = createWorkspaceMock.mock.calls[0][0]
    expect(payload).not.toHaveProperty("time_budget_minutes")
    expect(payload).not.toHaveProperty("restricted_environment")
  })
})

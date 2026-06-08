import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ExportGitHubModal } from "./ExportGitHubModal"
import {
  exportWorkspaceToGitHub,
  getGitHubInstallations,
  getGitHubPush,
} from "../../services/api"
import type { IntegrationPushRead } from "../../services/api"
import type { InstallationList } from "../../types/github"

vi.mock("../../services/api", () => ({
  exportWorkspaceToGitHub: vi.fn(),
  getGitHubInstallations: vi.fn(),
  getGitHubPush: vi.fn(),
  // The real helper digs the backend `detail` out of an axios error; the modal
  // only needs the fallback for our cases.
  getApiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const mockInstalls = vi.mocked(getGitHubInstallations)
const mockExport = vi.mocked(exportWorkspaceToGitHub)
const mockPush = vi.mocked(getGitHubPush)

function installed(suspended = false): InstallationList {
  return {
    installations: [
      {
        id: "inst-row-1",
        installation_id: 4242,
        account_login: "octocat",
        account_type: "Organization",
        repository_selection: "all",
        suspended,
      },
    ],
    on_legacy_oauth: false,
  }
}

function push(overrides: Partial<IntegrationPushRead> = {}): IntegrationPushRead {
  return {
    push_id: "push-1",
    status: "pending",
    repo_full_name: "octocat/my-spec",
    repo_url: "https://github.com/octocat/my-spec",
    issue_count: 4,
    pushed_at: null,
    ...overrides,
  }
}

function renderModal(props: Partial<Parameters<typeof ExportGitHubModal>[0]> = {}) {
  const onClose = vi.fn()
  render(
    <MemoryRouter>
      <ExportGitHubModal
        workspaceId="ws-1"
        workspaceName="My Spec"
        taskCount={4}
        onClose={onClose}
        {...props}
      />
    </MemoryRouter>,
  )
  return { onClose }
}

afterEach(() => {
  vi.clearAllMocks()
})

describe("ExportGitHubModal", () => {
  it("prompts to install when there is no active installation", async () => {
    mockInstalls.mockResolvedValue({ installations: [], on_legacy_oauth: false })

    renderModal()

    expect(
      await screen.findByText(/install the github app in settings/i),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument()
  })

  it("offers the Files vs PR-with-tests choice, with Files recommended + selected", async () => {
    mockInstalls.mockResolvedValue(installed())

    renderModal()

    const group = await screen.findByRole("radiogroup", { name: /export mode/i })
    const files = within(group).getByRole("radio", { name: /files/i })
    const pr = within(group).getByRole("radio", { name: /pr with tests/i })

    expect(files).toHaveAttribute("aria-checked", "true")
    expect(pr).toHaveAttribute("aria-checked", "false")
    expect(within(group).getByText(/recommended/i)).toBeInTheDocument()
    expect(
      within(group).getByText(/commit the four files \+ harness/i),
    ).toBeInTheDocument()
    expect(
      within(group).getByText(/open a pull request with failing tests/i),
    ).toBeInTheDocument()
  })

  it("slides in the concrete branch preview when PR-with-tests is chosen", async () => {
    mockInstalls.mockResolvedValue(installed())

    renderModal()

    const pr = await screen.findByRole("radio", { name: /pr with tests/i })
    expect(screen.queryByText(/specforge\/inc-1/i)).not.toBeInTheDocument()

    fireEvent.click(pr)

    expect(await screen.findByText(/specforge\/inc-1/i)).toBeInTheDocument()
  })

  it("submits with the installation_id + export_mode, then polls to a success state", async () => {
    mockInstalls.mockResolvedValue(installed())
    mockExport.mockResolvedValue(push({ status: "pending", repo_url: null }))
    // First poll still pending, then completed with the repo url.
    mockPush
      .mockResolvedValueOnce(push({ status: "pending" }))
      .mockResolvedValue(push({ status: "completed" }))

    renderModal()

    // Choose PR mode so we also assert the mode is forwarded.
    fireEvent.click(await screen.findByRole("radio", { name: /pr with tests/i }))
    fireEvent.click(screen.getByRole("button", { name: /export/i }))

    await waitFor(() =>
      expect(mockExport).toHaveBeenCalledWith(
        "ws-1",
        {
          repo_name: "my-spec",
          visibility: "public",
          installation_id: "inst-row-1",
          export_mode: "pr_with_tests",
        },
        expect.any(AbortSignal),
      ),
    )

    // Staged progress (not a bare spinner): the per-mode stages render.
    expect(await screen.findByText(/creating branch/i)).toBeInTheDocument()

    // Poll drives the terminal transition.
    expect(
      await screen.findByText(/pull request opened/i, undefined, { timeout: 4000 }),
    ).toBeInTheDocument()
    const link = screen.getByRole("link", {
      name: /github\.com\/octocat\/my-spec/i,
    })
    expect(link).toHaveAttribute("href", "https://github.com/octocat/my-spec")
  })

  it("does not consume a prior push's terminal status before the 202 resolves", async () => {
    mockInstalls.mockResolvedValue(installed())
    // Hold the POST so we can observe the window where a stale push could leak.
    let resolveExport: (v: IntegrationPushRead) => void = () => {}
    mockExport.mockReturnValue(
      new Promise<IntegrationPushRead>((resolve) => {
        resolveExport = resolve
      }),
    )
    // A prior push row already reads "completed" — it must NOT be polled yet.
    mockPush.mockResolvedValue(push({ status: "completed" }))

    renderModal()
    fireEvent.click(await screen.findByRole("button", { name: /export/i }))

    // Staged progress is showing, but polling is gated on the 202.
    expect(await screen.findByRole("list")).toBeInTheDocument()
    // Past a poll interval, the stale "completed" must not have been consumed.
    await new Promise((r) => setTimeout(r, 1700))
    expect(screen.queryByText(/exported to github/i)).not.toBeInTheDocument()
    expect(mockPush).not.toHaveBeenCalled()

    // Once the POST resolves, polling begins and the export completes.
    resolveExport(push({ status: "pending", repo_url: null }))
    expect(
      await screen.findByText(/exported to github/i, undefined, { timeout: 4000 }),
    ).toBeInTheDocument()
  })

  it("maps a 403 on submit back to the install prompt (no red error)", async () => {
    mockInstalls.mockResolvedValue(installed())
    mockExport.mockRejectedValue({ response: { status: 403 } })

    renderModal()

    fireEvent.click(await screen.findByRole("button", { name: /export/i }))

    expect(
      await screen.findByText(/no longer available|reconnect it in settings/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/^export failed/i)).not.toBeInTheDocument()
  })

  it("surfaces a failed export and offers retry", async () => {
    mockInstalls.mockResolvedValue(installed())
    mockExport.mockResolvedValue(push({ status: "pending", repo_url: null }))
    mockPush.mockResolvedValue(push({ status: "failed" }))

    renderModal()

    fireEvent.click(await screen.findByRole("button", { name: /export/i }))

    expect(
      await screen.findByText(/couldn't finish this export/i, undefined, {
        timeout: 4000,
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument()
  })
})

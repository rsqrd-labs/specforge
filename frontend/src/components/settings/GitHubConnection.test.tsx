import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import GitHubConnection from "./GitHubConnection"
import {
  getGitHubInstallUrl,
  getGitHubInstallations,
  revokeGitHubInstallation,
} from "../../services/api"
import type { InstallationOption } from "../../types/github"

vi.mock("../../services/api", () => ({
  getGitHubInstallations: vi.fn(),
  getGitHubInstallUrl: vi.fn(),
  revokeGitHubInstallation: vi.fn(),
}))

const mockList = vi.mocked(getGitHubInstallations)
const mockInstallUrl = vi.mocked(getGitHubInstallUrl)
const mockRevoke = vi.mocked(revokeGitHubInstallation)

function install(overrides: Partial<InstallationOption> = {}): InstallationOption {
  return {
    id: "inst-row-1",
    installation_id: 4242,
    account_login: "octocat",
    account_type: "Organization",
    repository_selection: "all",
    suspended: false,
    ...overrides,
  }
}

/** Surfaces the current location.search so the param-cleanup can be asserted. */
function LocationProbe() {
  const location = useLocation()
  return <span data-testid="search">{location.search}</span>
}

function renderPanel(initialEntries: string[] = ["/settings"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <GitHubConnection />
      <LocationProbe />
    </MemoryRouter>,
  )
}

// jsdom's window.location is read-only; swap in a writable stub to capture the
// install redirect.
let originalLocation: Location
beforeEach(() => {
  originalLocation = window.location
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: { href: "" } as Location,
  })
})
afterEach(() => {
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: originalLocation,
  })
  vi.clearAllMocks()
})

describe("GitHubConnection", () => {
  it("offers the App install with a single scope line when not installed", async () => {
    mockList.mockResolvedValue({ installations: [], on_legacy_oauth: false })

    renderPanel()

    expect(
      await screen.findByRole("button", { name: /install github app/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/branches, issues, and pull requests/i),
    ).toBeInTheDocument()
    // No legacy nag for a clean first-time user.
    expect(screen.queryByText(/old connection/i)).not.toBeInTheDocument()
  })

  it("shows the installed account and repository selection when installed", async () => {
    mockList.mockResolvedValue({
      installations: [install({ account_login: "octocat", repository_selection: "all" })],
      on_legacy_oauth: false,
    })

    renderPanel()

    expect(await screen.findByText(/installed on @octocat/i)).toBeInTheDocument()
    expect(screen.getByText("all repositories")).toBeInTheDocument()
    const manage = screen.getByRole("link", { name: /manage on github/i })
    expect(manage).toHaveAttribute(
      "href",
      "https://github.com/organizations/octocat/settings/installations/4242",
    )
  })

  it("renders 'selected repositories' for a selected-repo installation", async () => {
    mockList.mockResolvedValue({
      installations: [install({ repository_selection: "selected", account_type: "User" })],
      on_legacy_oauth: false,
    })

    renderPanel()

    expect(await screen.findByText("selected repositories")).toBeInTheDocument()
    // Personal-account installs point at the user settings install URL.
    expect(
      screen.getByRole("link", { name: /manage on github/i }),
    ).toHaveAttribute(
      "href",
      "https://github.com/settings/installations/4242",
    )
  })

  it("prompts a legacy-OAuth user to migrate, without a red alarm", async () => {
    mockList.mockResolvedValue({ installations: [], on_legacy_oauth: true })

    renderPanel()

    const notice = await screen.findByRole("note")
    expect(notice).toHaveTextContent(/old connection/i)
    expect(notice).toHaveTextContent(/re-install the github app/i)
    // It is a note, never an alert (no red banner).
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /install github app/i }),
    ).toBeInTheDocument()
  })

  it("morphs the button to 'Opening GitHub…' and redirects on install", async () => {
    const user = userEvent.setup()
    mockList.mockResolvedValue({ installations: [], on_legacy_oauth: false })

    // Hold the URL resolution so the transient "Opening GitHub…" state is observable.
    let resolveUrl: (v: string) => void = () => {}
    mockInstallUrl.mockReturnValue(
      new Promise<string>((resolve) => {
        resolveUrl = resolve
      }),
    )

    renderPanel()
    await user.click(
      await screen.findByRole("button", { name: /install github app/i }),
    )

    expect(
      await screen.findByRole("button", { name: /opening github…/i }),
    ).toBeInTheDocument()

    resolveUrl("https://github.com/apps/thought2build/installations/new")
    await waitFor(() =>
      expect(window.location.href).toBe(
        "https://github.com/apps/thought2build/installations/new",
      ),
    )
  })

  it("surfaces a calm message (no redirect) when the App is not configured", async () => {
    const user = userEvent.setup()
    mockList.mockResolvedValue({ installations: [], on_legacy_oauth: false })
    mockInstallUrl.mockResolvedValue(null) // 503 → App disabled

    renderPanel()
    await user.click(
      await screen.findByRole("button", { name: /install github app/i }),
    )

    expect(await screen.findByRole("alert")).toHaveTextContent(/not configured/i)
    expect(window.location.href).toBe("") // never navigated
  })

  it("disconnects an installation and re-fetches to the not-installed state", async () => {
    const user = userEvent.setup()
    mockList
      .mockResolvedValueOnce({ installations: [install()], on_legacy_oauth: false })
      .mockResolvedValueOnce({ installations: [], on_legacy_oauth: false })
    mockRevoke.mockResolvedValue()

    renderPanel()

    await user.click(await screen.findByRole("button", { name: /disconnect/i }))
    await user.click(screen.getByRole("button", { name: /yes, disconnect/i }))

    await waitFor(() => expect(mockRevoke).toHaveBeenCalledWith("inst-row-1"))
    // Re-fetch flipped the panel back to the install CTA.
    expect(
      await screen.findByRole("button", { name: /install github app/i }),
    ).toBeInTheDocument()
    expect(mockList).toHaveBeenCalledTimes(2)
  })

  it("re-fetches and clears the ?github_installed=true return param", async () => {
    mockList.mockResolvedValue({
      installations: [install()],
      on_legacy_oauth: false,
    })

    renderPanel(["/settings?github_installed=true"])

    expect(await screen.findByText(/installed on @octocat/i)).toBeInTheDocument()
    // The one-time return param is stripped from the URL after handling.
    await waitFor(() =>
      expect(screen.getByTestId("search")).toHaveTextContent(""),
    )
    expect(screen.getByTestId("search").textContent).not.toContain(
      "github_installed",
    )
  })
})

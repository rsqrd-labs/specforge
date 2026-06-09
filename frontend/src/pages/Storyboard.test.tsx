import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import {
  createMemoryRouter,
  Link,
  RouterProvider,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DEFAULT_TEST_PERMISSIONS, makeStoryboardPayload } from "../components/storyboard/testPayload"
import { getStoryboard } from "../services/api"
import type { StoryboardDetail } from "../types/storyboard"
import Storyboard from "./Storyboard"

vi.mock("../services/api", () => ({
  getStoryboard: vi.fn(),
  getApiErrorMessage: vi.fn((_error: unknown, fallback = "Storyboard failed") => fallback),
}))

function makeStoryboard(overrides: Partial<StoryboardDetail> = {}): StoryboardDetail {
  return {
    id: "storyboard-1",
    workspace_id: "workspace-1",
    version: 1,
    status: "ready",
    title: "Launch Storyboard",
    theme: "Copper circuit cards",
    content: makeStoryboardPayload({ title: "Launch Storyboard" }),
    source_map: {},
    permissions: DEFAULT_TEST_PERMISSIONS,
    public_share_enabled: false,
    public_share_slug: null,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    ...overrides,
  }
}

function WorkspaceRoute() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  return (
    <main>
      <h1>Workspace {id}</h1>
      <button
        type="button"
        onClick={() => {
          navigate("/storyboards/storyboard-1", {
            state: { workspaceId: id },
          })
        }}
      >
        Open Storyboard
      </button>
    </main>
  )
}

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location">{location.pathname}</span>
}

function renderStoryboardFlow(initialEntries = ["/dashboard"]) {
  const router = createMemoryRouter(
    [
      {
        path: "/dashboard",
        element: (
          <main>
            <h1>Dashboard</h1>
            <Link to="/workspace/workspace-1">Open Workspace</Link>
            <LocationProbe />
          </main>
        ),
      },
      {
        path: "/workspace/:id",
        element: (
          <>
            <WorkspaceRoute />
            <LocationProbe />
          </>
        ),
      },
      {
        path: "/storyboards/:id",
        element: (
          <>
            <Storyboard />
            <LocationProbe />
          </>
        ),
      },
    ],
    { initialEntries },
  )

  return {
    router,
    user: userEvent.setup(),
    ...render(<RouterProvider router={router} />),
  }
}

beforeEach(() => {
  vi.mocked(getStoryboard).mockReset()
  vi.mocked(getStoryboard).mockResolvedValue(makeStoryboard())
})

describe("Storyboard navigation", () => {
  it("returns to dashboard after leaving storyboard for the originating workspace", async () => {
    const { router, user } = renderStoryboardFlow()

    await user.click(screen.getByRole("link", { name: /open workspace/i }))
    expect(screen.getByTestId("location")).toHaveTextContent("/workspace/workspace-1")

    await user.click(screen.getByRole("button", { name: /open storyboard/i }))
    expect(await screen.findByRole("button", { name: /back to workspace/i })).toBeInTheDocument()
    expect(screen.getByTestId("location")).toHaveTextContent("/storyboards/storyboard-1")

    await user.click(screen.getByRole("button", { name: /back to workspace/i }))
    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/workspace/workspace-1")
    })

    await act(async () => {
      await router.navigate(-1)
    })
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument()
    expect(screen.getByTestId("location")).toHaveTextContent("/dashboard")
  })

  it("uses a replace fallback for direct storyboard links without workspace history", async () => {
    const { user } = renderStoryboardFlow(["/storyboards/storyboard-1"])

    await user.click(await screen.findByRole("button", { name: /back to workspace/i }))

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/workspace/workspace-1")
    })
  })
})

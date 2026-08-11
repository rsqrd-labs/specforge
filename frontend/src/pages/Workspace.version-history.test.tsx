import { render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import Workspace from "./Workspace"
import {
  getGitHubInstallations,
  getGitHubIntegration,
  getLatestStoryboard,
  getStageEval,
  getStageVersions,
  getWorkspace,
} from "../services/api"
import { useStageStore } from "../store/stageStore"
import { useWorkspaceStore } from "../store/workspaceStore"
import type { EvalResult, Stage, StageType, StageVersion } from "../types/stage"
import type { WorkspaceWithStages } from "../types/workspace"

vi.mock("../components/shared/ActionAlert", () => ({
  useActionAlert: () => ({ showAlert: vi.fn(), dismissAlert: vi.fn() }),
}))

vi.mock("../hooks/useCredits", () => ({
  useCredits: () => ({ balance: null, isLoading: false }),
}))

vi.mock("../hooks/useGitHubSync", () => ({
  useGitHubSync: () => ({
    data: null,
    repoFullName: null,
    repoUrl: null,
    connection: "disconnected",
    loading: false,
    resyncing: false,
    resync: vi.fn(),
    refreshing: false,
    refreshError: null,
    refreshFromGitHub: vi.fn(),
  }),
}))

vi.mock("../hooks/useReconnectPoll", () => ({
  useReconnectPoll: vi.fn(),
}))

vi.mock("../hooks/useStream", () => ({
  useStream: () => ({ start: vi.fn(), isStreaming: false, error: null }),
}))

vi.mock("../services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/api")>()
  return {
    ...actual,
    getGitHubInstallations: vi.fn(),
    getGitHubIntegration: vi.fn(),
    getLatestStoryboard: vi.fn(),
    getStageEval: vi.fn(),
    getStageVersions: vi.fn(),
    getWorkspace: vi.fn(),
  }
})

const mockGetWorkspace = vi.mocked(getWorkspace)
const mockGetStageVersions = vi.mocked(getStageVersions)
const mockGetStageEval = vi.mocked(getStageEval)
const mockGetLatestStoryboard = vi.mocked(getLatestStoryboard)
const mockGetGitHubInstallations = vi.mocked(getGitHubInstallations)
const mockGetGitHubIntegration = vi.mocked(getGitHubIntegration)

const NOW = "2026-07-20T10:00:00Z"

function makeStage(type: StageType, currentVersion: number): Stage {
  return {
    id: `stage-${type}`,
    workspace_id: "ws-1",
    type,
    content: `# ${type.toUpperCase()}\n\nCurrent artifact`,
    status: "draft",
    current_version: currentVersion,
    eval_result: null,
    finalised_at: null,
    gap_patch_used: false,
    review_gate_acknowledged: false,
    created_at: NOW,
    updated_at: NOW,
  }
}

function makeWorkspace(stage: Stage): WorkspaceWithStages {
  return {
    id: "ws-1",
    user_id: "user-1",
    name: "Version history workspace",
    problem_statement:
      "A sufficiently detailed source brief for exercising the workspace layout.",
    status: "active",
    created_at: NOW,
    updated_at: NOW,
    stages: [stage],
  }
}

function makeEval(stage: Stage): EvalResult {
  return {
    id: `eval-${stage.id}`,
    stage_version_id: `version-${stage.current_version}`,
    stage_type: stage.type,
    overall_score: null,
    completeness: null,
    clarity: null,
    coverage_percent: null,
    uncovered_reqs: null,
    deferred_reqs: null,
    tasks_without_ref: null,
    flagged: false,
    created_at: NOW,
  }
}

function makeVersions(stage: Stage): StageVersion[] {
  return Array.from({ length: stage.current_version }, (_, index) => ({
    id: `${stage.id}-version-${index + 1}`,
    stage_id: stage.id,
    version: index + 1,
    content: `Version ${index + 1}`,
    created_by: index === 0 ? "ai" : "user",
    created_at: NOW,
  }))
}

async function renderWorkspace(stage: Stage) {
  const workspace = makeWorkspace(stage)
  mockGetWorkspace.mockResolvedValue(workspace)
  mockGetStageEval.mockResolvedValue(makeEval(stage))
  mockGetStageVersions.mockResolvedValue(makeVersions(stage))

  render(
    <MemoryRouter initialEntries={["/workspace/ws-1"]}>
      <Routes>
        <Route path="/workspace/:id" element={<Workspace />} />
      </Routes>
    </MemoryRouter>,
  )

  await waitFor(() => expect(mockGetWorkspace).toHaveBeenCalledWith("ws-1"))
}

beforeEach(() => {
  useWorkspaceStore.setState({
    currentWorkspace: null,
    isLoading: false,
  })
  useStageStore.setState({
    stages: {},
    streamingContent: {},
    activeStream: null,
    qualityGate: {},
    streamProgress: {},
    pendingReset: {},
  })
  mockGetLatestStoryboard.mockResolvedValue(null)
  mockGetGitHubInstallations.mockResolvedValue({
    installations: [],
    on_legacy_oauth: false,
  })
  mockGetGitHubIntegration.mockResolvedValue({
    connected: false,
    github_username: null,
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("Workspace version-history placement", () => {
  it.each([
    [1, false],
    [2, true],
  ] as const)(
    "renders the non-spec history rail only when current_version is %i",
    async (currentVersion, expectedVisible) => {
      await renderWorkspace(makeStage("plan", currentVersion))

      const planHeadings = await screen.findAllByRole("heading", { name: "PLAN" })
      expect(planHeadings.length).toBeGreaterThan(0)
      if (expectedVisible) {
        expect(await screen.findByText("Version History")).toBeInTheDocument()
        expect(document.querySelector(".workspace-right-panel")).toBeInTheDocument()
      } else {
        expect(screen.queryByText("Version History")).not.toBeInTheDocument()
        expect(document.querySelector(".workspace-right-panel")).not.toBeInTheDocument()
        expect(mockGetStageVersions).not.toHaveBeenCalled()
      }
    },
  )

  it("places spec history beneath the source brief in the left column", async () => {
    await renderWorkspace(makeStage("spec", 2))

    const historyTitle = await screen.findByText("Version History")
    const sourceColumn = historyTitle.closest(".spec-source-column")
    expect(sourceColumn).not.toBeNull()
    expect(
      within(sourceColumn as HTMLElement).getByRole("heading", {
        name: "Problem Statement",
      }),
    ).toBeInTheDocument()
  })
})

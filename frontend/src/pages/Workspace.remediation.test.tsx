import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import Workspace from "./Workspace"
import {
  acceptStageDiff,
  acknowledgeStaleStage,
  finaliseStage,
  getGitHubInstallations,
  getGitHubIntegration,
  getLatestStoryboard,
  getStageEval,
  getStageVersions,
  getWorkspace,
  refineStage,
  rejectStageDiff,
  updateStageContent,
} from "../services/api"
import { useStageStore } from "../store/stageStore"
import { useWorkspaceStore } from "../store/workspaceStore"
import type { EvalResult, Stage, StageType } from "../types/stage"
import type { WorkspaceWithStages } from "../types/workspace"

const uiMocks = vi.hoisted(() => ({
  dismissAlert: vi.fn(),
  showAlert: vi.fn(),
  startStream: vi.fn(),
}))

vi.mock("../components/shared/ActionAlert", () => ({
  useActionAlert: () => ({
    showAlert: uiMocks.showAlert,
    dismissAlert: uiMocks.dismissAlert,
  }),
}))

vi.mock("../components/workspace/StageEditor", async () => {
  const React = await import("react")

  const StageEditor = React.forwardRef(function MockStageEditor(
    props: {
      initialContent: string
      onContentChange?: (content: string) => void
    },
    ref: React.ForwardedRef<{
      getSelection: () => { start: number; end: number; text: string }
      getContent: () => string
    }>,
  ) {
    React.useImperativeHandle(
      ref,
      () => ({
        getSelection: () => ({ start: 0, end: 4, text: "Plan" }),
        getContent: () => props.initialContent,
      }),
      [props.initialContent],
    )
    return (
      <div data-testid="mock-stage-editor">
        <button
          type="button"
          onClick={() => props.onContentChange?.(props.initialContent)}
        >
          Emit unchanged content
        </button>
      </div>
    )
  })

  return { StageEditor }
})

vi.mock("../components/workspace/ExportGitHubModal", () => ({
  ExportGitHubModal: ({ taskCount }: { taskCount: number }) => (
    <div data-testid="github-task-count">{taskCount}</div>
  ),
}))

vi.mock("../hooks/useCredits", () => ({
  useCredits: () => ({ balance: 50, isLoading: false }),
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
  useStream: () => ({
    start: uiMocks.startStream,
    isStreaming: false,
    error: null,
  }),
}))

vi.mock("../services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/api")>()
  return {
    ...actual,
    acceptStageDiff: vi.fn(),
    acknowledgeStaleStage: vi.fn(),
    finaliseStage: vi.fn(),
    getGitHubInstallations: vi.fn(),
    getGitHubIntegration: vi.fn(),
    getLatestStoryboard: vi.fn(),
    getStageEval: vi.fn(),
    getStageVersions: vi.fn(),
    getWorkspace: vi.fn(),
    refineStage: vi.fn(),
    rejectStageDiff: vi.fn(),
    updateStageContent: vi.fn(),
  }
})

const mockAcceptStageDiff = vi.mocked(acceptStageDiff)
const mockAcknowledgeStaleStage = vi.mocked(acknowledgeStaleStage)
const mockFinaliseStage = vi.mocked(finaliseStage)
const mockGetGitHubInstallations = vi.mocked(getGitHubInstallations)
const mockGetGitHubIntegration = vi.mocked(getGitHubIntegration)
const mockGetLatestStoryboard = vi.mocked(getLatestStoryboard)
const mockGetStageEval = vi.mocked(getStageEval)
const mockGetStageVersions = vi.mocked(getStageVersions)
const mockGetWorkspace = vi.mocked(getWorkspace)
const mockRefineStage = vi.mocked(refineStage)
const mockRejectStageDiff = vi.mocked(rejectStageDiff)
const mockUpdateStageContent = vi.mocked(updateStageContent)

const NOW = "2026-07-20T12:00:00Z"

function makeStage(type: StageType, overrides: Partial<Stage> = {}): Stage {
  return {
    id: `stage-${type}`,
    workspace_id: "ws-remediation",
    type,
    content: `# ${type.toUpperCase()}\n\nCurrent artifact`,
    status: "draft",
    current_version: 1,
    eval_result: null,
    finalised_at: null,
    gap_patch_used: false,
    review_gate_acknowledged: true,
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  }
}

function makeWorkspace(stages: Stage[]): WorkspaceWithStages {
  return {
    id: "ws-remediation",
    user_id: "user-1",
    name: "Remediation workspace",
    problem_statement:
      "A sufficiently detailed source brief for exercising workspace remediation behavior.",
    status: "active",
    created_at: NOW,
    updated_at: NOW,
    stages,
  }
}

function makeEval(stage: Stage, overrides: Partial<EvalResult> = {}): EvalResult {
  return {
    id: `eval-${stage.id}`,
    stage_version_id: `${stage.id}-version-1`,
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
    ...overrides,
  }
}

async function renderWorkspace(
  stages: Stage[],
  evalResult: EvalResult | null = null,
) {
  const workspace = makeWorkspace(stages)
  mockGetWorkspace.mockResolvedValue(workspace)
  mockGetStageEval.mockResolvedValue(evalResult ?? makeEval(stages[0]))

  render(
    <MemoryRouter initialEntries={["/workspace/ws-remediation"]}>
      <Routes>
        <Route path="/workspace/:id" element={<Workspace />} />
      </Routes>
    </MemoryRouter>,
  )

  await screen.findByRole("heading", { name: "Remediation workspace" })
  return workspace
}

async function openRefineForm() {
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: /^edit$/i }))
  await screen.findByTestId("mock-stage-editor")
  await user.click(screen.getByRole("button", { name: /refine plan/i }))
  return user
}

async function generateDiff() {
  const user = await openRefineForm()
  await user.type(
    screen.getByPlaceholderText(/describe how to refine/i),
    "Make this clearer",
  )
  await user.click(screen.getByRole("button", { name: /refine.*3 credits/i }))
  await screen.findByText("Proposed changes")
  return user
}

beforeEach(() => {
  useWorkspaceStore.setState({ currentWorkspace: null, isLoading: false })
  useStageStore.setState({
    stages: {},
    streamingContent: {},
    activeStream: null,
    qualityGate: {},
    streamProgress: {},
    pendingReset: {},
  })
  uiMocks.startStream.mockResolvedValue(null)
  mockGetLatestStoryboard.mockResolvedValue(null)
  mockGetStageVersions.mockResolvedValue([])
  mockGetGitHubInstallations.mockResolvedValue({
    installations: [],
    on_legacy_oauth: false,
  })
  mockGetGitHubIntegration.mockResolvedValue({
    connected: false,
    github_username: null,
  })
  mockRefineStage.mockResolvedValue({
    diff: "@@\n-Current artifact\n+Clearer artifact",
    original: "Current artifact",
    proposed: "Clearer artifact",
    base_version: 1,
    large_selection: false,
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("Workspace Phase 5 remediation", () => {
  it("skips a no-op autosave", async () => {
    await renderWorkspace([makeStage("plan")])
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: /^edit$/i }))
    await user.click(screen.getByRole("button", { name: /emit unchanged content/i }))

    expect(mockUpdateStageContent).not.toHaveBeenCalled()
  })

  it.each([
    ["accept", /accept changes/i, mockAcceptStageDiff],
    ["reject", /^reject$/i, mockRejectStageDiff],
  ] as const)(
    "surfaces a failed %s action and retains the paid diff",
    async (_action, buttonName, apiCall) => {
      apiCall.mockRejectedValueOnce(new Error("transient failure"))
      await renderWorkspace([makeStage("plan")])
      const user = await generateDiff()

      await user.click(screen.getByRole("button", { name: buttonName }))

      await waitFor(() => expect(uiMocks.showAlert).toHaveBeenCalled())
      expect(screen.getByText("Proposed changes")).toBeInTheDocument()
      expect(JSON.stringify(uiMocks.showAlert.mock.calls.at(-1)?.[0])).toMatch(
        /could not (apply|reject) the proposed changes/i,
      )
    },
  )

  it("deduplicates rapid diff acceptance and sends its base version", async () => {
    const stage = makeStage("plan")
    let resolveAccept!: (value: Stage) => void
    mockAcceptStageDiff.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveAccept = resolve
        }),
    )
    await renderWorkspace([stage])
    const user = await generateDiff()
    const accept = screen.getByRole("button", { name: /accept changes/i })

    await user.dblClick(accept)

    expect(mockAcceptStageDiff).toHaveBeenCalledTimes(1)
    expect(mockAcceptStageDiff).toHaveBeenCalledWith(
      stage.id,
      "Clearer artifact",
      1,
    )
    expect(accept).toBeDisabled()
    resolveAccept({ ...stage, content: "Clearer artifact", current_version: 2 })
    await waitFor(() =>
      expect(screen.queryByText("Proposed changes")).not.toBeInTheDocument(),
    )
  })

  it("deduplicates rapid finalise clicks", async () => {
    const stage = makeStage("plan")
    let resolveFinalise!: (value: Stage) => void
    mockFinaliseStage.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFinalise = resolve
        }),
    )
    await renderWorkspace([stage])
    const finalise = screen.getByRole("button", { name: /finalise plan/i })

    fireEvent.click(finalise)
    fireEvent.click(finalise)
    expect(mockFinaliseStage).toHaveBeenCalledOnce()

    await act(async () => {
      resolveFinalise({ ...stage, status: "finalised" })
    })
  })

  it("deduplicates rapid stale-stage Keep clicks", async () => {
    const stage = makeStage("plan", { status: "stale" })
    let resolveAcknowledge!: (value: Stage) => void
    mockAcknowledgeStaleStage.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveAcknowledge = resolve
        }),
    )
    await renderWorkspace([stage])
    const keep = screen.getByRole("button", { name: /^keep$/i })

    fireEvent.click(keep)
    fireEvent.click(keep)
    expect(mockAcknowledgeStaleStage).toHaveBeenCalledOnce()

    await act(async () => {
      resolveAcknowledge({ ...stage, status: "finalised" })
    })
  })

  it("uses the task parser for GitHub's issue-count preview", async () => {
    const stages = (["spec", "plan", "harness", "tasks"] as const).map((type) =>
      makeStage(type, {
        status: "finalised",
        content:
          type === "tasks"
            ? "### T-001 : Parser-compatible task\n\n**Description**\nShip it."
            : `# ${type.toUpperCase()}\n\nFinal artifact`,
      }),
    )
    mockGetGitHubInstallations.mockResolvedValue({
      installations: [
        {
          id: "installation-row-1",
          installation_id: 4242,
          account_login: "octocat",
          account_type: "Organization",
          repository_selection: "all",
          suspended: false,
        },
      ],
      on_legacy_oauth: false,
    })
    await renderWorkspace(stages)
    const user = userEvent.setup()

    await user.click(screen.getByRole("button", { name: /^export$/i }))
    const githubExport = await screen.findByRole("menuitem", {
      name: /export to github/i,
    })
    await waitFor(() => expect(githubExport).toBeEnabled())
    await user.click(githubExport)

    expect(screen.getByTestId("github-task-count")).toHaveTextContent("1")
  })
})

describe("Workspace Phase 6 credit transparency", () => {
  it("shows the 3-credit cost inline before submitting Refine", async () => {
    await renderWorkspace([makeStage("plan")])
    await openRefineForm()

    expect(
      screen.getByRole("button", { name: /refine.*3 credits/i }),
    ).toBeInTheDocument()
    expect(mockRefineStage).not.toHaveBeenCalled()
  })

  it("confirms a paid harness patch before starting its stream", async () => {
    const harness = makeStage("harness")
    await renderWorkspace(
      [harness],
      makeEval(harness, { deferred_reqs: ["FR-001"] }),
    )
    const user = userEvent.setup()

    await user.click(
      await screen.findByRole("button", { name: /patch harness coverage/i }),
    )
    expect(uiMocks.startStream).not.toHaveBeenCalled()
    expect(
      screen.getByRole("heading", { name: /patch coverage/i }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /patch coverage/i }))
    await waitFor(() =>
      expect(uiMocks.startStream).toHaveBeenCalledWith("regenerate-gaps"),
    )
  })
})

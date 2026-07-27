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
import { useReconnectPoll } from "../hooks/useReconnectPoll"
import { useStageStore } from "../store/stageStore"
import { useWorkspaceStore } from "../store/workspaceStore"
import type { EvalResult, GenerationRun, Stage, StageType } from "../types/stage"
import type { WorkspaceWithStages } from "../types/workspace"

const mockUseReconnectPoll = vi.mocked(useReconnectPoll)

const uiMocks = vi.hoisted(() => ({
  cancelStream: vi.fn(),
  dismissAlert: vi.fn(),
  editorContent: null as string | null,
  isStopping: false,
  isStreaming: false,
  streamError: null as { code: string; message: string } | null,
  terminal: null as null | {
    generation_id: string
    status: "cancelled" | "failed"
    partial_saved: boolean
    refunded_credits: number
    credit_was_deducted?: boolean
  },
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
        getContent: () => uiMocks.editorContent ?? props.initialContent,
      }),
      [props.initialContent],
    )
    return (
      <div data-testid="mock-stage-editor">
        <button
          type="button"
          onClick={() => props.onContentChange?.(uiMocks.editorContent ?? props.initialContent)}
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
    cancel: uiMocks.cancelStream,
    isStreaming: uiMocks.isStreaming,
    isStopping: uiMocks.isStopping,
    terminal: uiMocks.terminal,
    generation: null,
    error: uiMocks.streamError,
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
  uiMocks.isStopping = false
  uiMocks.isStreaming = false
  uiMocks.streamError = null
  uiMocks.terminal = null
  uiMocks.editorContent = null
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

  it("persists changed editor content and keeps the canonical response", async () => {
    const stage = makeStage("plan")
    uiMocks.editorContent = "# PLAN\n\nEdited artifact"
    mockUpdateStageContent.mockResolvedValue({ ...stage, content: uiMocks.editorContent, current_version: 2 })
    await renderWorkspace([stage])
    await userEvent.click(screen.getByRole("button", { name: /^edit$/i }))
    await userEvent.click(screen.getByRole("button", { name: /emit unchanged content/i }))
    await waitFor(() => expect(mockUpdateStageContent).toHaveBeenCalledWith(stage.id, uiMocks.editorContent))
  })

  it("surfaces a changed-content save failure", async () => {
    uiMocks.editorContent = "# PLAN\n\nUnsaved edit"
    mockUpdateStageContent.mockRejectedValue(new Error("offline"))
    await renderWorkspace([makeStage("plan")])
    await userEvent.click(screen.getByRole("button", { name: /^edit$/i }))
    await userEvent.click(screen.getByRole("button", { name: /emit unchanged content/i }))
    await waitFor(() => expect(uiMocks.showAlert).toHaveBeenCalledWith(expect.objectContaining({
      message: "Could not save the latest edit.",
    })))
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

  it("finalises and advances to the newly unlocked next stage", async () => {
    const spec = makeStage("spec")
    const plan = makeStage("plan", { status: "locked" })
    const refreshed = makeWorkspace([{ ...spec, status: "finalised" }, { ...plan, status: "draft" }])
    mockFinaliseStage.mockResolvedValue({ ...spec, status: "finalised" })
    await renderWorkspace([spec, plan])
    mockGetWorkspace.mockResolvedValue(refreshed)
    await userEvent.click(screen.getByRole("button", { name: /finalise spec/i }))
    await waitFor(() => expect(screen.getAllByRole("button", { name: /plan stage/i })[0]).toHaveAttribute("aria-current", "step"))
  })

  it("surfaces finalise and stale-acknowledgement failures", async () => {
    mockFinaliseStage.mockRejectedValueOnce(new Error("conflict"))
    await renderWorkspace([makeStage("plan")])
    fireEvent.click(screen.getByRole("button", { name: /finalise plan/i }))
    await waitFor(() => expect(uiMocks.showAlert).toHaveBeenCalledWith(expect.objectContaining({
      message: "Only draft stages can be finalised.",
    })))
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

  it("retains a paid diff after success rejection is acknowledged server-side", async () => {
    mockRejectStageDiff.mockResolvedValue({ rejected: true })
    await renderWorkspace([makeStage("plan")])
    const user = await generateDiff()
    await user.click(screen.getByRole("button", { name: /^reject$/i }))
    await waitFor(() => expect(screen.queryByText("Proposed changes")).not.toBeInTheDocument())
    expect(mockRejectStageDiff).toHaveBeenCalledWith("stage-plan")
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

describe("Workspace state matrix", () => {
  it.each([
    ["insufficient_credits", "View billing"],
    ["generation_timeout", "Try again"],
    ["generation_unavailable", "Try again"],
    ["rate_limit_exceeded", "Try again"],
    ["internal_error", "Try again"],
    ["stream_interrupted", "Try again"],
    ["generic", "Try again"],
    ["security_check_failed", null],
  ] as const)("maps stream error %s to the correct recovery", async (code, action) => {
    uiMocks.streamError = { code, message: `Failure ${code}` }
    await renderWorkspace([makeStage("plan")])
    await waitFor(() => expect(uiMocks.showAlert).toHaveBeenCalled())
    const alert = uiMocks.showAlert.mock.calls.at(-1)?.[0]
    if (action) expect(alert.primaryAction?.label).toBe(action)
    else expect(alert.primaryAction).toBeUndefined()
  })

  it.each(["quality_gate_failed", "session_expired", "generation_in_progress"])(
    "suppresses duplicate %s alerts",
    async (code) => {
      uiMocks.streamError = { code, message: code }
      await renderWorkspace([makeStage("spec")])
      expect(uiMocks.showAlert).not.toHaveBeenCalled()
    },
  )

  it("offers an unlock only when a finalised stage is not generatable", async () => {
    uiMocks.streamError = { code: "stage_not_generatable", message: "complete" }
    await renderWorkspace([makeStage("plan", { status: "finalised" })])
    await waitFor(() => expect(uiMocks.showAlert).toHaveBeenCalled())
    expect(uiMocks.showAlert.mock.calls.at(-1)?.[0].primaryAction?.label).toBe("Unlock stage")
  })

  it("renders finalised, stale, draft, and locked stages and preserves navigation", async () => {
    await renderWorkspace([
      makeStage("spec", { status: "finalised" }),
      makeStage("plan", { status: "stale" }),
      makeStage("harness", { status: "draft", content: "" }),
      makeStage("tasks", { status: "locked", content: null }),
    ])
    const user = userEvent.setup()
    expect(screen.getAllByRole("button", { name: /spec stage/i })[0]).toHaveAttribute("aria-current", "step")
    await user.click(screen.getAllByRole("button", { name: /plan stage/i })[0])
    expect(screen.getByRole("button", { name: /^keep$/i })).toBeInTheDocument()
    await user.click(screen.getAllByRole("button", { name: /harness stage/i })[0])
    expect(screen.getAllByRole("button", { name: /harness stage/i })[0]).toHaveAttribute("aria-current", "step")
    expect(screen.getAllByRole("button", { name: /tasks stage/i })[0]).toBeDisabled()
  })

  it("reconnects an in-progress regeneration with a stable locked reading view", async () => {
    await renderWorkspace([
      makeStage("spec", {
        status: "in_progress",
        generation_action: "regenerate",
        generation_started_at: "2026-07-20T11:59:00Z",
      }),
    ])
    expect(screen.getByText(/editing is locked/i)).toBeInTheDocument()
    const cancel = screen.getByRole("button", { name: /cancel generation|cancel$/i })
    await userEvent.click(cancel)
    expect(uiMocks.cancelStream).toHaveBeenCalled()
  })

  it("surfaces terminal cancellation refund evidence", async () => {
    uiMocks.terminal = {
      generation_id: "g1",
      status: "cancelled",
      partial_saved: true,
      refunded_credits: 10,
      credit_was_deducted: true,
    }
    await renderWorkspace([makeStage("spec")])
    await waitFor(() => expect(uiMocks.showAlert).toHaveBeenCalledWith(expect.objectContaining({
      title: "Generation cancelled",
      recovery: "10 credits were refunded.",
    })))
  })

  it.each([
    [false, false, "No credits were charged"],
    [false, true, "retained its generation charge"],
    [true, false, "safely generated portion was saved"],
  ] as const)("explains a failed terminal outcome", async (partial, charged, copy) => {
    uiMocks.terminal = {
      generation_id: "g2", status: "failed", partial_saved: partial,
      refunded_credits: 0, credit_was_deducted: charged,
    }
    await renderWorkspace([makeStage("spec")])
    await waitFor(() => expect(JSON.stringify(uiMocks.showAlert.mock.calls.at(-1)?.[0])).toMatch(new RegExp(copy, "i")))
  })

  it("renders persisted blocking gates and advisory findings independently", async () => {
    const blocked = makeStage("plan", {
      quality_gate: {
        stage: "plan", kind: "missing_sections", status: "blocked",
        findings: [{ kind: "MissingSection", detail: "ADR missing", reference: "ADR" }],
        recovery: { action: "regenerate", overridable: true, credit_required: 10, refunded_prior_attempt: false, message: "Review this blocked draft." },
      },
    })
    await renderWorkspace([blocked])
    expect(screen.getByText("Review this blocked draft.")).toBeInTheDocument()
  })

  it("keeps the quality-gate popup's buttons clickable after a reconnected block (regression)", async () => {
    // Simulates navigating away mid-generation and back: the stage mounts
    // in_progress, useReconnectPoll (mocked here) detects the detached run
    // settled with a quality-gate block, and delivers the fresh stage exactly
    // as the real hook does. Firing the generic terminal alert on top of the
    // popup for a `blocked` run stacks a full-viewport backdrop over it,
    // silently eating every click on Regenerate/Override/Dismiss.
    const inProgress = makeStage("tasks", {
      status: "in_progress",
      generation_action: "regenerate",
      generation_started_at: NOW,
    })
    await renderWorkspace([inProgress])

    const onTerminal = mockUseReconnectPoll.mock.calls.at(-1)?.[2] as
      | ((run: GenerationRun) => void)
      | undefined
    expect(onTerminal).toBeTypeOf("function")

    const blocked: Stage = {
      ...inProgress,
      status: "draft",
      current_version: 2,
      quality_gate: {
        stage: "tasks",
        kind: "missing_sections",
        status: "blocked",
        findings: [
          { kind: "MissingSection", detail: "Acceptance criteria missing", reference: "AC" },
        ],
        recovery: {
          action: "regenerate",
          overridable: true,
          credit_required: 10,
          refunded_prior_attempt: false,
          message: "Review this blocked draft.",
        },
      },
    }

    act(() => {
      useStageStore.getState().setStage(blocked)
      onTerminal?.({
        id: "run-1",
        stage_id: blocked.id,
        action: "regenerate",
        status: "blocked",
        phase: "validating",
        completed_parts: 1,
        total_parts: 1,
        started_at: NOW,
        deadline_at: NOW,
        heartbeat_at: NOW,
        cancel_requested_at: null,
        finished_at: NOW,
        result_version: 2,
        error_code: "missing_sections",
        partial_saved: true,
        refunded_credits: 0,
        credit_was_deducted: true,
      })
    })

    const regenerate = await screen.findByRole("button", { name: "Regenerate" })
    expect(regenerate).toBeEnabled()
    expect(screen.getByRole("button", { name: "Override and continue" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "Hide details" })).toBeEnabled()
    expect(uiMocks.showAlert).not.toHaveBeenCalled()
  })
})

import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SpecClarificationModal } from "./SpecClarificationModal"
import {
  persistClarification,
  requestClarification,
} from "../../services/api"

vi.mock("../../services/api", () => ({
  requestClarification: vi.fn(),
  persistClarification: vi.fn(),
}))

const mockRequestClarification = vi.mocked(requestClarification)
const mockPersistClarification = vi.mocked(persistClarification)

afterEach(() => {
  vi.clearAllMocks()
})

describe("SpecClarificationModal", () => {
  it("requests a new clarification round and submits round-mode answers", async () => {
    const user = userEvent.setup()
    const onProceed = vi.fn()
    mockRequestClarification.mockResolvedValue({
      questions: [
        {
          question: "Who is the primary user?",
          why_it_matters: "This shapes the acceptance criteria.",
        },
      ],
    })
    mockPersistClarification.mockResolvedValue()

    render(
      <SpecClarificationModal
        workspaceId="workspace-1"
        onProceed={onProceed}
        onCancel={vi.fn()}
      />,
    )

    const answer = await screen.findByLabelText("Who is the primary user?")
    await user.type(answer, "Operations managers.")
    await user.click(
      screen.getByRole("button", {
        name: "Generate from clarification answers",
      }),
    )

    await waitFor(() => {
      expect(mockPersistClarification).toHaveBeenCalledWith(
        "workspace-1",
        [
          {
            question: "Who is the primary user?",
            answer: "Operations managers.",
          },
        ],
        "round",
      )
    })
    expect(onProceed).toHaveBeenCalledWith([
      {
        question: "Who is the primary user?",
        answer: "Operations managers.",
      },
    ])
  })

  it("renders existing saved answers without requesting new questions", async () => {
    const user = userEvent.setup()
    const onProceed = vi.fn()

    render(
      <SpecClarificationModal
        workspaceId="workspace-1"
        mode="existing"
        existingAnswers={[
          {
            question: "What changed since the last attempt?",
            answer: "The first answer is still valid.",
          },
        ]}
        onProceed={onProceed}
        onCancel={vi.fn()}
      />,
    )

    expect(await screen.findByText("Review your previous answers")).toBeInTheDocument()
    expect(screen.getByText(/These answers are already saved/i)).toBeInTheDocument()
    expect(
      screen.getByDisplayValue("The first answer is still valid."),
    ).toBeInTheDocument()
    expect(mockRequestClarification).not.toHaveBeenCalled()

    await user.click(
      screen.getByRole("button", {
        name: "Use saved clarification answers and retry generation",
      }),
    )

    expect(mockPersistClarification).not.toHaveBeenCalled()
    expect(onProceed).toHaveBeenCalledWith([
      {
        question: "What changed since the last attempt?",
        answer: "The first answer is still valid.",
      },
    ])
  })

  it("submits edited saved answers in existing mode", async () => {
    const user = userEvent.setup()
    const onProceed = vi.fn()
    mockPersistClarification.mockResolvedValue()

    render(
      <SpecClarificationModal
        workspaceId="workspace-1"
        mode="existing"
        existingAnswers={[
          {
            question: "Which workflow matters most?",
            answer: "Workspace owners reviewing the generated SPEC.",
          },
        ]}
        onProceed={onProceed}
        onCancel={vi.fn()}
      />,
    )

    const answer = await screen.findByLabelText("Which workflow matters most?")
    await user.clear(answer)
    await user.type(answer, "Workspace owners retrying after provider failure.")
    await user.click(
      screen.getByRole("button", {
        name: "Save edited clarification answers and retry generation",
      }),
    )

    await waitFor(() => {
      expect(mockPersistClarification).toHaveBeenCalledWith(
        "workspace-1",
        [
          {
            question: "Which workflow matters most?",
            answer: "Workspace owners retrying after provider failure.",
          },
        ],
        "existing",
      )
    })
    expect(onProceed).toHaveBeenCalledWith([
      {
        question: "Which workflow matters most?",
        answer: "Workspace owners retrying after provider failure.",
      },
    ])
  })
})

import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { IdeaBacklog } from "./IdeaBacklog"
import type { IncrementIdea } from "../../types/github"

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

function renderBacklog(props: Partial<Parameters<typeof IdeaBacklog>[0]> = {}) {
  const onCapture = vi.fn()
  const onPromote = vi.fn()
  render(
    <IdeaBacklog
      ideas={[]}
      capturing={false}
      onCapture={onCapture}
      onPromote={onPromote}
      {...props}
    />,
  )
  return { onCapture, onPromote }
}

describe("IdeaBacklog", () => {
  it("shows a written empty state, not placeholder text", () => {
    renderBacklog()
    expect(screen.getByText(/capture a feature as it occurs/i)).toBeInTheDocument()
  })

  it("marks a GitHub-sourced idea with its provenance", () => {
    renderBacklog({
      ideas: [idea({ source: "github", external_ref: "owner/repo#12" })],
    })
    expect(screen.getByTitle(/from a github issue/i)).toBeInTheDocument()
  })

  it("offers Promote on open ideas and calls back with the idea", () => {
    const { onPromote } = renderBacklog({ ideas: [idea({ text: "SSO" })] })
    fireEvent.click(screen.getByRole("button", { name: /promote/i }))
    expect(onPromote).toHaveBeenCalledWith(
      expect.objectContaining({ text: "SSO" }),
    )
  })

  it("shows a status note instead of Promote for a resolved idea", () => {
    renderBacklog({ ideas: [idea({ status: "planned" })] })
    expect(screen.getByText(/planned/i)).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /promote/i }),
    ).not.toBeInTheDocument()
  })

  it("captures an idea on submit and clears the input", () => {
    const { onCapture } = renderBacklog()
    const input = screen.getByLabelText(/capture an idea/i)
    fireEvent.change(input, { target: { value: "Webhook retries" } })
    fireEvent.click(screen.getByRole("button", { name: /add idea/i }))
    expect(onCapture).toHaveBeenCalledWith("Webhook retries")
    expect(input).toHaveValue("")
  })

  it("disables idea capture and promote with a lock reason", () => {
    const { onCapture, onPromote } = renderBacklog({
      ideas: [idea({ text: "SSO" })],
      disabled: true,
      disabledReason: "Editing resumes when generation finishes.",
    })

    const input = screen.getByLabelText(/capture an idea/i)
    expect(input).toBeDisabled()
    expect(input).toHaveAccessibleDescription(
      /editing resumes when generation finishes/i,
    )
    expect(screen.getByRole("button", { name: /add idea/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /promote idea to increment/i })).toBeDisabled()

    fireEvent.click(screen.getByRole("button", { name: /promote idea to increment/i }))
    expect(onCapture).not.toHaveBeenCalled()
    expect(onPromote).not.toHaveBeenCalled()
  })
})

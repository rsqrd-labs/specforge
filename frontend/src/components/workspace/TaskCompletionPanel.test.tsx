import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import { TaskCompletionPanel, type SyncConnection } from "./TaskCompletionPanel"
import type { SyncState, TaskSyncState } from "../../types/github"

function task(overrides: Partial<TaskSyncState> = {}): TaskSyncState {
  return {
    task_ref: "T-001",
    issue_number: 1,
    state: "open",
    done_via: null,
    done_at: null,
    synced_at: null,
    human_ref: null,
    title: null,
    ...overrides,
  }
}

function syncState(overrides: Partial<SyncState> = {}): SyncState {
  const tasks = overrides.tasks ?? [
    task({ task_ref: "T-001", issue_number: 11, state: "done", done_via: "pr_merge" }),
    task({ task_ref: "T-002", issue_number: 12, state: "done", done_via: "manual" }),
    task({ task_ref: "T-003", issue_number: 13, state: "open" }),
  ]
  const shipped = overrides.shipped ?? tasks.filter((t) => t.state === "done").length
  return {
    push_id: "push-1",
    status: "completed",
    out_of_sync: false,
    shipped,
    total: overrides.total ?? tasks.length,
    tasks,
    ...overrides,
  }
}

function renderPanel(
  props: Partial<React.ComponentProps<typeof TaskCompletionPanel>> = {},
) {
  const onResync = vi.fn()
  const merged: React.ComponentProps<typeof TaskCompletionPanel> = {
    data: syncState(),
    repoFullName: "octo/spec",
    repoUrl: "https://github.com/octo/spec",
    connection: "connected" as SyncConnection,
    loading: false,
    resyncing: false,
    onResync,
    ...props,
  }
  return {
    onResync,
    ...render(
      <MemoryRouter>
        <TaskCompletionPanel {...merged} />
      </MemoryRouter>,
    ),
  }
}

describe("TaskCompletionPanel", () => {
  it("renders the shipped/total progress and per-task issue deep links", () => {
    renderPanel()

    const progress = screen.getByRole("progressbar")
    expect(progress).toHaveAttribute("aria-valuenow", "2")
    expect(progress).toHaveAttribute("aria-valuemax", "3")
    // The fraction lives once — on the header + the progressbar's label; the
    // duplicate "X of Y tasks shipped" caption was removed.
    expect(progress).toHaveAccessibleName(/2 of 3 tasks shipped/i)
    expect(screen.queryByText(/tasks shipped/i)).toBeNull()

    const issueLink = screen.getByRole("link", { name: /issue #11 on github/i })
    expect(issueLink).toHaveAttribute(
      "href",
      "https://github.com/octo/spec/issues/11",
    )
  })

  it("shows the human T-NNN ref chip and the task title, never the hash", () => {
    renderPanel({
      data: syncState({
        tasks: [
          task({
            task_ref: "task-abc123",
            issue_number: 7,
            human_ref: "T-007",
            title: "Wire the API client",
          }),
        ],
      }),
    })

    expect(screen.getByText("T-007")).toBeInTheDocument()
    expect(screen.getByText("Wire the API client")).toBeInTheDocument()
    // The opaque content-hash ref is never rendered.
    expect(screen.queryByText(/task-abc123/)).toBeNull()
  })

  it("falls back to the issue number when a task has no resolved title", () => {
    renderPanel({
      data: syncState({
        tasks: [task({ issue_number: 42, human_ref: null, title: null })],
      }),
    })

    // Heading falls back to "Issue #42"; there is no ref chip.
    expect(screen.getByText("Issue #42")).toBeInTheDocument()
  })

  it("marks a merged-PR task with the via-PR (lotus) accent", () => {
    const { container } = renderPanel()
    // T-001 closed via pr_merge → lotus check + 'Shipped via PR' sublabel.
    expect(screen.getByText("Shipped via PR")).toBeInTheDocument()
    expect(container.querySelector(".ws-sync-check.done.via-pr")).not.toBeNull()
  })

  it("caps the list to a glance and links to the full status screen", () => {
    const tasks = Array.from({ length: 8 }, (_, i) =>
      task({
        task_ref: `task-${i}`,
        issue_number: i + 1,
        human_ref: `T-00${i + 1}`,
        title: `Task ${i + 1}`,
        state: "open",
      }),
    )
    const { container } = renderPanel({
      data: syncState({ tasks, shipped: 0 }),
      detailHref: "/workspace/ws-1/github",
    })

    // Only the first six rows render; the rest defer to the detail screen.
    expect(container.querySelectorAll(".ws-sync-task")).toHaveLength(6)
    const viewAll = screen.getByRole("link", { name: /view all 8 tasks/i })
    expect(viewAll).toHaveAttribute("href", "/workspace/ws-1/github")
  })

  it("shows the drift banner and triggers resync when out_of_sync", async () => {
    const user = userEvent.setup()
    const { onResync } = renderPanel({ data: syncState({ out_of_sync: true }) })

    expect(screen.getByText(/tasks changed since the last push/i)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /sync changed tasks/i }))
    expect(onResync).toHaveBeenCalledOnce()
  })

  it("disables drift resync with a clear lock reason", async () => {
    const user = userEvent.setup()
    const { onResync } = renderPanel({
      data: syncState({ out_of_sync: true }),
      disabled: true,
      disabledReason: "Editing resumes when generation finishes.",
    })

    const sync = screen.getByRole("button", { name: /sync changed tasks/i })
    expect(sync).toBeDisabled()
    expect(sync).toHaveAccessibleDescription(
      /editing resumes when generation finishes/i,
    )

    await user.click(sync)
    expect(onResync).not.toHaveBeenCalled()
  })

  it("folds to a sync-paused line when the install is suspended", () => {
    renderPanel({ connection: "suspended" })

    expect(screen.getByText(/sync paused/i)).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /reconnect github/i }),
    ).toHaveAttribute("href", "/settings")
    // The progress hero is not rendered in the disconnected fold.
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument()
  })

  it("renders a two-row skeleton on first load (no spinner)", () => {
    const { container } = renderPanel({ data: null, loading: true })

    expect(container.querySelector(".ws-sync-skeleton")).not.toBeNull()
    expect(container.querySelectorAll(".ws-sync-skeleton-row")).toHaveLength(2)
  })

  it("renders nothing for a workspace that was never pushed", () => {
    const { container } = renderPanel({ data: null, loading: false })
    expect(container.firstChild).toBeNull()
  })

  it("highlights only true open→done transitions, not rows already shipped on mount", () => {
    const { container, rerender } = renderPanel({
      data: syncState({
        tasks: [
          task({ task_ref: "task-1", human_ref: "T-001", issue_number: 11, state: "done", done_via: "manual" }),
          task({ task_ref: "task-2", human_ref: "T-002", issue_number: 12, state: "open" }),
        ],
      }),
    })
    // Nothing flashes on the first render — the baseline is just established.
    expect(container.querySelector(".ws-sync-task.just-shipped")).toBeNull()

    // T-002 flips to done on the next poll → it (and only it) highlights once.
    rerender(
      <MemoryRouter>
        <TaskCompletionPanel
          data={syncState({
            tasks: [
              task({ task_ref: "task-1", human_ref: "T-001", issue_number: 11, state: "done", done_via: "manual" }),
              task({ task_ref: "task-2", human_ref: "T-002", issue_number: 12, state: "done", done_via: "manual" }),
            ],
          })}
          repoFullName="octo/spec"
          repoUrl="https://github.com/octo/spec"
          connection="connected"
          loading={false}
          resyncing={false}
          onResync={vi.fn()}
        />
      </MemoryRouter>,
    )
    const flashed = container.querySelectorAll(".ws-sync-task.just-shipped")
    expect(flashed).toHaveLength(1)
    expect(flashed[0].textContent).toContain("T-002")
  })
})

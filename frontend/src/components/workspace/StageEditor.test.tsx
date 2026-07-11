import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { act } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useStageStore } from "../../store/stageStore"
import type { Stage, StageStatus } from "../../types/stage"
import { StageEditor } from "./StageEditor"

function resetStore() {
  useStageStore.setState({
    stages: {},
    streamingContent: {},
    activeStream: null,
    qualityGate: {},
    streamProgress: {},
    pendingReset: {},
  })
}

function seedStage(id: string, status: StageStatus, content = ""): Stage {
  const stage: Stage = {
    id,
    workspace_id: "ws-1",
    type: "harness",
    content,
    status,
    current_version: status === "in_progress" ? 0 : 1,
    finalised_at: null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    created_at: "2026-07-11T00:00:00Z",
    updated_at: "2026-07-11T00:00:00Z",
  }
  useStageStore.getState().setStage(stage)
  return stage
}

describe("StageEditor", () => {
  it("reacts to readOnly changes after mount and explains the lock", async () => {
    const onContentChange = vi.fn()
    const { container, rerender } = render(
      <StageEditor
        stageId="stage-1"
        initialContent="Initial content"
        onContentChange={onContentChange}
      />,
    )

    const editor = await waitFor(() => {
      const node = container.querySelector(".cm-content")
      expect(node).not.toBeNull()
      return node as HTMLElement
    })
    expect(editor).toHaveAttribute("contenteditable", "true")

    rerender(
      <StageEditor
        stageId="stage-1"
        initialContent="Initial content"
        readOnly
        readOnlyReason="Editing paused. Editing resumes when generation finishes."
        onContentChange={onContentChange}
      />,
    )

    const lockedEditor = await waitFor(() => {
      const node = container.querySelector(".cm-content")
      expect(node).not.toBeNull()
      expect(node).toHaveAttribute("contenteditable", "false")
      return node as HTMLElement
    })
    expect(screen.getByText(/editing resumes when generation finishes/i)).toBeInTheDocument()

    fireEvent.input(lockedEditor, { target: { textContent: "Changed while locked" } })
    expect(onContentChange).not.toHaveBeenCalled()
  })

  describe("hydrates from the live streaming buffer on remount", () => {
    beforeEach(resetStore)
    afterEach(resetStore)

    it("seeds the editor from streamingContent when the persisted content is still empty", async () => {
      // Mid-generation: tokens live only in the store; the persisted stage
      // content is still "" (status in_progress). A remount (navigate away and
      // back) must show the buffered draft, not a blank editor.
      seedStage("stage-1", "in_progress")
      const store = useStageStore.getState()
      store.startStream("stage-1")
      store.appendToken("stage-1", "# Harness\n\nBuffered partial draft")

      const { container } = render(
        <StageEditor
          stageId="stage-1"
          initialContent=""
          readOnly
          readOnlyReason="Editing paused."
        />,
      )

      const editor = await waitFor(() => {
        const node = container.querySelector(".cm-content")
        expect(node).not.toBeNull()
        return node as HTMLElement
      })
      expect(editor.textContent).toContain("Buffered partial draft")
    })

    it("stays on the buffered draft through a silent phase (no further tokens)", async () => {
      // The original bug: return during the post-stream quality-gate/critic
      // window (heartbeats only, no tokens until `done`) → editor was blank.
      seedStage("stage-1", "in_progress")
      const store = useStageStore.getState()
      store.startStream("stage-1")
      store.appendToken("stage-1", "silent-phase draft")

      const { container } = render(
        <StageEditor stageId="stage-1" initialContent="" readOnly />,
      )

      const editor = await waitFor(() => {
        const node = container.querySelector(".cm-content")
        expect(node).not.toBeNull()
        return node as HTMLElement
      })
      // Present immediately on mount — no token needed to reveal it.
      expect(editor.textContent).toBe("silent-phase draft")
    })

    it("appends only the delta of a future token without duplicating the seeded buffer", async () => {
      // Regression: lastStreamedRef must be seeded to the buffer so the next
      // token appends `content.slice(prev.length)` — not the whole buffer again.
      seedStage("stage-1", "in_progress")
      const store = useStageStore.getState()
      store.startStream("stage-1")
      store.appendToken("stage-1", "AAA")

      const { container } = render(
        <StageEditor stageId="stage-1" initialContent="" readOnly />,
      )

      const editor = await waitFor(() => {
        const node = container.querySelector(".cm-content")
        expect(node).not.toBeNull()
        return node as HTMLElement
      })
      expect(editor.textContent).toBe("AAA")

      // A future token arrives after the remount.
      act(() => {
        useStageStore.getState().appendToken("stage-1", "BBB")
      })

      await waitFor(() => {
        expect(editor.textContent).toBe("AAABBB")
      })
    })

    it("full-replaces the doc when a pending reset rewrites the buffer shorter", async () => {
      // stream_reset (completion repair / canonical replay): the next token
      // overwrites the buffer rather than appending. The editor must swap to the
      // replacement, never concatenate the stale draft with it.
      seedStage("stage-1", "in_progress")
      const store = useStageStore.getState()
      store.startStream("stage-1")
      store.appendToken("stage-1", "# Old long buffered draft that is stale")

      const { container } = render(
        <StageEditor stageId="stage-1" initialContent="" readOnly />,
      )

      const editor = await waitFor(() => {
        const node = container.querySelector(".cm-content")
        expect(node).not.toBeNull()
        return node as HTMLElement
      })
      expect(editor.textContent).toContain("Old long buffered draft")

      act(() => {
        useStageStore.getState().clearStreamContent("stage-1")
        useStageStore.getState().appendToken("stage-1", "# New")
      })

      await waitFor(() => {
        expect(editor.textContent).toBe("# New")
      })
    })

    it("IGNORES a stale leaked buffer once the stage has settled to draft (CONFIRMED-1)", async () => {
      // A Workspace unmount mid-stream can leak a partial into the store. Once
      // the stage settles to `draft`, the persisted content IS the final
      // artifact — the editor must show that, never the stale partial (which a
      // keystroke would otherwise persist over the finished artifact).
      seedStage("stage-1", "draft", "FINAL ARTIFACT")
      // Leaked orphan buffer, never cleared:
      useStageStore.setState((s) => ({
        streamingContent: { ...s.streamingContent, "stage-1": "stale partial" },
      }))

      const { container } = render(
        <StageEditor stageId="stage-1" initialContent="FINAL ARTIFACT" />,
      )

      const editor = await waitFor(() => {
        const node = container.querySelector(".cm-content")
        expect(node).not.toBeNull()
        return node as HTMLElement
      })
      expect(editor.textContent).toBe("FINAL ARTIFACT")
      expect(editor.textContent).not.toContain("stale partial")
    })

    it("does not append below the old artifact on regenerate (CONFIRMED-2)", async () => {
      // Regenerate: startStream sets an EMPTY buffer, status flips to
      // in_progress, then the status-keyed remount seeds the doc. The first
      // token must replace from an empty doc, not concatenate below the old one.
      seedStage("stage-1", "in_progress", "OLD ARTIFACT")
      useStageStore.getState().startStream("stage-1") // buffer = ""

      const { container } = render(
        <StageEditor stageId="stage-1" initialContent="OLD ARTIFACT" readOnly />,
      )

      const editor = await waitFor(() => {
        const node = container.querySelector(".cm-content")
        expect(node).not.toBeNull()
        return node as HTMLElement
      })
      // Empty doc pre-token (the full-card overlay covers it in the real UI).
      expect(editor.textContent).toBe("")

      act(() => {
        useStageStore.getState().appendToken("stage-1", "NEW")
      })

      await waitFor(() => {
        expect(editor.textContent).toBe("NEW")
      })
    })
  })
})

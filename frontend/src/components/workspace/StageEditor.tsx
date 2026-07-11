import { markdown } from "@codemirror/lang-markdown"
import { EditorView } from "@codemirror/view"
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react"
import { useStageStore } from "../../store/stageStore"

export interface StageEditorHandle {
  getSelection: () => { start: number; end: number; text: string } | null
  getContent: () => string
}

interface StageEditorProps {
  stageId: string
  initialContent: string
  readOnly?: boolean
  readOnlyReason?: string
  onContentChange?: (content: string) => void
}

export const StageEditor = forwardRef<StageEditorHandle, StageEditorProps>(
  function StageEditor(
    { stageId, initialContent, readOnly = false, readOnlyReason, onContentChange },
    ref,
  ) {
    const containerRef = useRef<HTMLDivElement>(null)
    const viewRef = useRef<EditorView | null>(null)
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const lastStreamedRef = useRef<string>("")
    const readOnlyRef = useRef(readOnly)
    const onContentChangeRef = useRef(onContentChange)
    const contentRef = useRef(initialContent)
    const mountedStageIdRef = useRef<string | null>(null)
    const readOnlyReasonId = `${stageId}-editor-readonly-reason`

    useEffect(() => {
      readOnlyRef.current = readOnly
    }, [readOnly])

    useEffect(() => {
      onContentChangeRef.current = onContentChange
    }, [onContentChange])

    useImperativeHandle(ref, () => ({
      getSelection() {
        const view = viewRef.current
        if (!view) return null
        const { from, to } = view.state.selection.main
        if (from === to) return null
        const text = view.state.sliceDoc(from, to)
        return { start: from, end: to, text }
      },
      getContent() {
        return viewRef.current?.state.doc.toString() ?? initialContent
      },
    }))

    useEffect(() => {
      if (!containerRef.current) return
      if (mountedStageIdRef.current !== stageId) {
        mountedStageIdRef.current = stageId
        // Hydrate from the live streaming buffer if a generation for this stage
        // is mid-flight. Navigating between stages remounts the editor while the
        // SSE stream keeps accumulating tokens into the store; without seeding
        // from that buffer the doc starts empty and — because the streaming
        // subscription below fires only on FUTURE writes — stays blank through
        // any silent phase (post-stream quality gate / critic / repair) until
        // `done`, so a returning user sees the generated draft "erased".
        //
        // The buffer is authoritative ONLY while THIS stage is generating
        // (`status === "in_progress"`). Two failure modes this gates out:
        //   • Stale orphan: a Workspace unmount mid-stream can leak a partial
        //     into the store; once the stage settles to `draft` the reconnect
        //     poll holds the FINAL artifact, so hydrating from the leaked partial
        //     would show — and, on a keystroke, persist — a truncated draft.
        //   • Regenerate: `startStream` sets an EMPTY buffer and the status flips
        //     to in_progress before the first token; keying ownership on the
        //     buffer *key* (not its length) seeds an empty doc so the first token
        //     replaces from scratch instead of appending below the old artifact.
        const state = useStageStore.getState()
        const isGenerating = state.stages[stageId]?.status === "in_progress"
        const buffered = state.streamingContent[stageId]
        const ownsStream = isGenerating && typeof buffered === "string"
        contentRef.current = ownsStream ? buffered : initialContent
        lastStreamedRef.current = ownsStream ? buffered : ""
      }

      const view = new EditorView({
        doc: contentRef.current,
        extensions: [
          markdown(),
          EditorView.editable.of(!readOnly),
          EditorView.updateListener.of((update) => {
            if (!update.docChanged) return
            contentRef.current = update.state.doc.toString()
            if (readOnlyRef.current) return
            if (debounceRef.current) clearTimeout(debounceRef.current)
            debounceRef.current = setTimeout(() => {
              onContentChangeRef.current?.(update.state.doc.toString())
            }, 500)
          }),
          EditorView.theme({
            "&": { height: "100%", fontSize: "14px" },
            ".cm-content": { fontFamily: "'Plus Jakarta Sans', sans-serif", lineHeight: "1.6" },
            ".cm-focused": { outline: "none" },
          }),
        ],
        parent: containerRef.current,
      })

      viewRef.current = view

      return () => {
        contentRef.current = view.state.doc.toString()
        view.destroy()
        viewRef.current = null
        if (debounceRef.current) {
          clearTimeout(debounceRef.current)
          debounceRef.current = null
          if (!readOnly) {
            onContentChangeRef.current?.(contentRef.current)
          }
        }
      }
    }, [readOnly, stageId])

    useEffect(() => {
      const unsubscribe = useStageStore.subscribe(
        (state) => state.streamingContent[stageId],
        (content) => {
          const view = viewRef.current
          if (!view || content === undefined) return

          const prev = lastStreamedRef.current
          if (content.startsWith(prev)) {
            const newTokens = content.slice(prev.length)
            if (newTokens) {
              view.dispatch({
                changes: {
                  from: view.state.doc.length,
                  insert: newTokens,
                },
              })
              lastStreamedRef.current = content
            }
          } else {
            // stream_reset / canonical replay: the buffer was rewritten
            // rather than appended — replace the whole document.
            view.dispatch({
              changes: {
                from: 0,
                to: view.state.doc.length,
                insert: content,
              },
            })
            lastStreamedRef.current = content
          }
        },
      )
      return unsubscribe
    }, [stageId])

    return (
      <div
        className={`stage-editor-shell${readOnly ? " is-readonly" : ""}`}
        aria-describedby={readOnly && readOnlyReason ? readOnlyReasonId : undefined}
      >
        {readOnly && readOnlyReason ? (
          <div id={readOnlyReasonId} className="stage-editor-readonly-note">
            {readOnlyReason}
          </div>
        ) : null}
        <div ref={containerRef} className="stage-editor-mount" />
      </div>
    )
  },
)

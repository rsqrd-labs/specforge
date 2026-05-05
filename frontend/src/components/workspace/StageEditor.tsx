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
}

interface StageEditorProps {
  stageId: string
  initialContent: string
  readOnly?: boolean
  onContentChange?: (content: string) => void
}

export const StageEditor = forwardRef<StageEditorHandle, StageEditorProps>(
  function StageEditor(
    { stageId, initialContent, readOnly = false, onContentChange },
    ref,
  ) {
    const containerRef = useRef<HTMLDivElement>(null)
    const viewRef = useRef<EditorView | null>(null)
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const lastStreamedRef = useRef<string>("")

    useImperativeHandle(ref, () => ({
      getSelection() {
        const view = viewRef.current
        if (!view) return null
        const { from, to } = view.state.selection.main
        if (from === to) return null
        const text = view.state.sliceDoc(from, to)
        return { start: from, end: to, text }
      },
    }))

    useEffect(() => {
      if (!containerRef.current) return

      const view = new EditorView({
        doc: initialContent,
        extensions: [
          markdown(),
          EditorView.editable.of(!readOnly),
          EditorView.updateListener.of((update) => {
            if (!update.docChanged || readOnly) return
            if (debounceRef.current) clearTimeout(debounceRef.current)
            debounceRef.current = setTimeout(() => {
              onContentChange?.(update.state.doc.toString())
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
      lastStreamedRef.current = ""

      return () => {
        view.destroy()
        viewRef.current = null
        if (debounceRef.current) clearTimeout(debounceRef.current)
      }
    }, [stageId])

    useEffect(() => {
      const unsubscribe = useStageStore.subscribe(
        (state) =>
          typeof state.streamingContent === "string"
            ? state.streamingContent
            : state.streamingContent[stageId],
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
          }
        },
      )
      return unsubscribe
    }, [stageId])

    return (
      <div
        ref={containerRef}
        className="h-full w-full bg-surface overflow-auto"
      />
    )
  },
)

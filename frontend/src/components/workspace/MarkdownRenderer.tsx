import { Component, type ReactNode } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"

interface MarkdownRendererProps {
  content: string
  variant?: "default" | "harness"
}

// ---------------------------------------------------------------------------
// Error boundary
// ---------------------------------------------------------------------------

interface BoundaryState {
  hasError: boolean
}

class RendererErrorBoundary extends Component<
  { content: string; children: ReactNode },
  BoundaryState
> {
  state: BoundaryState = { hasError: false }

  static getDerivedStateFromError(): BoundaryState {
    return { hasError: true }
  }

  componentDidCatch(err: Error) {
    console.error("[MarkdownRenderer] render error:", err)
  }

  // Reset when the parent supplies new content so a fresh generation attempt
  // doesn't stay stuck showing the fallback.
  componentDidUpdate(prev: { content: string }) {
    if (this.state.hasError && prev.content !== this.props.content) {
      this.setState({ hasError: false })
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="md-prose">
          <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {this.props.content}
          </pre>
        </div>
      )
    }
    return this.props.children
  }
}

// ---------------------------------------------------------------------------
// Markdown normalisation helpers
// ---------------------------------------------------------------------------

function looksLikeDirectoryTree(value: string): boolean {
  const lines = value
    .split("\n")
    .map((line) => line.trimEnd())
    .filter(Boolean)

  if (lines.length < 2) return false

  return lines.some((line) => /[─-╿]/.test(line)) || lines[0].endsWith("/")
}

/**
 * Repairs two fence-related failure patterns that cause all content after a
 * code block to render as raw text:
 *
 * 1. Doubled opening fence — the LLM emits the opening fence twice
 *    (e.g. ```mermaid\n```mermaid). The duplicate becomes the first line of
 *    code content; the real closing ``` ends the outer block; and a stray ```
 *    is left behind that opens a new unclosed block swallowing the rest of the
 *    document.
 *
 * 2. Unclosed fence — generation was interrupted or the LLM simply forgot the
 *    closing ```. Everything after the opening fence renders as a code block.
 *    Fixed by appending the missing closing fence at the end of the document.
 *
 * Uses a line-by-line state machine so fence context is never ambiguous.
 */
export function normalizeDoubledFences(content: string): string {
  const lines = content.replace(/\r\n/g, "\n").split("\n")
  const out: string[] = []
  let insideFence: string | null = null // expected closing fence (backticks, no lang)
  let doubled = false // true when the current block had its opening deduplicated

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    if (insideFence === null) {
      // Outside a block — look for an opening fence (3+ backticks + optional lang)
      const m = line.match(/^([ \t]*`{3,})([a-zA-Z0-9]*)$/)
      if (m) {
        const fullFence = (m[1] + m[2]).trimEnd()
        const closeFence = m[1].trimEnd() // closing fence carries no language
        const nextTrimmed = lines[i + 1]?.trimEnd()
        if (nextTrimmed !== undefined && nextTrimmed === fullFence) {
          // Doubled opening — emit once, skip the duplicate
          out.push(line)
          i++
          insideFence = closeFence
          doubled = true
        } else {
          out.push(line)
          insideFence = closeFence
          doubled = false
        }
        continue
      }
    } else {
      // Inside a block — look for the matching closing fence
      if (line.trimEnd() === insideFence) {
        out.push(line)
        insideFence = null
        // A doubled opening leaves an extra closing fence immediately after.
        // Skip it so it doesn't open a new unclosed block.
        if (doubled && lines[i + 1]?.trimEnd() === line.trimEnd()) {
          i++
        }
        doubled = false
        continue
      }
    }
    out.push(line)
  }

  // If the document ends with an unclosed block, close it so all prior content
  // renders as normal markdown rather than staying trapped inside a code block.
  if (insideFence !== null) {
    out.push(insideFence)
  }

  return out.join("\n")
}

export function normalizeHarnessMarkdown(content: string): string {
  const fileHeadingMatch = content.match(/^##\s+File:\s+/m)
  if (!fileHeadingMatch || fileHeadingMatch.index === undefined) return content

  const prefix = content.slice(0, fileHeadingMatch.index).trim()
  const rest = content.slice(fileHeadingMatch.index).trimStart()
  if (!prefix || prefix.startsWith("```")) return content

  const tree = prefix.replace(/```\s*$/, "").trim()
  if (!looksLikeDirectoryTree(tree)) return content

  return `## Directory structure\n\n\`\`\`text\n${tree}\n\`\`\`\n\n${rest}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function textFromChildren(children: unknown): string {
  if (typeof children === "string") return children
  if (Array.isArray(children)) return children.map(textFromChildren).join("")
  if (children && typeof children === "object" && "props" in children) {
    const props = (children as { props?: { children?: unknown } }).props
    return textFromChildren(props?.children)
  }
  return ""
}

export function MarkdownRenderer({
  content,
  variant = "default",
}: MarkdownRendererProps) {
  const fixed = normalizeDoubledFences(content)
  const renderedContent =
    variant === "harness" ? normalizeHarnessMarkdown(fixed) : fixed

  return (
    <RendererErrorBoundary content={content}>
      <div className={variant === "harness" ? "md-prose md-prose-harness" : "md-prose"}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[[rehypeHighlight, { ignoreMissing: true }]]}
          components={{
            h2({ children, node: _node, ...props }) {
              const label = textFromChildren(children)
              const isFileHeading = label.trim().toLowerCase().startsWith("file:")
              return (
                <h2
                  {...props}
                  className={isFileHeading ? "md-file-heading" : undefined}
                >
                  {children}
                </h2>
              )
            },
            pre({ children, node: _node, ...props }) {
              const value = textFromChildren(children)
              const isTree = looksLikeDirectoryTree(value)
              return (
                <pre {...props} className={isTree ? "md-directory-tree" : undefined}>
                  {children}
                </pre>
              )
            },
          }}
        >
          {renderedContent}
        </ReactMarkdown>
      </div>
    </RendererErrorBoundary>
  )
}

import { Children, Component, isValidElement, type ReactNode } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"
import rehypeSanitize from "rehype-sanitize"

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

  // Unicode box-drawing characters used by `tree` command
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
 * 3. Orphaned closer — a lone ``` with no language appears outside any fence
 *    block before a section heading. Treating it as an opener would swallow the
 *    entire section below it into a code block. Detected and skipped.
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

        // Orphaned closer: no language tag and the next non-blank line is a
        // section heading (2+ hashes). This ``` is a stray from the LLM and
        // must not be treated as a fence opener — skip it.
        if (m[2] === "") {
          let j = i + 1
          while (j < lines.length && lines[j].trim() === "") j++
          if (j < lines.length && /^#{2,}\s/.test(lines[j])) {
            continue
          }
        }

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

/**
 * Normalises harness markdown into a form that renders correctly.
 *
 * The harness LLM prompt instructs the model to output:
 *   ## File Tree        — unfenced or fenced directory listing
 *   ## Files
 *   ### File: path/to/file — per-file heading (three hashes)
 *   ```lang ... ```
 *
 * Two normalisation passes run here so that normalizeDoubledFences never
 * sees ambiguous lone ``` markers:
 *
 * Pass 1 — "## File Tree" section: if the tree is bare text (not yet fenced),
 * wrap it in ```text … ```.
 *
 * Pass 2 — Legacy format: bare tree before the first file heading (## or ###),
 * possibly ending with a lone ```. Wrap the tree and emit a directory heading.
 *
 * In both cases an already-fenced tree (any opening ```) is left untouched.
 */
export function normalizeHarnessMarkdown(content: string): string {
  // Pass 1: handle "## File Tree" section
  const fileTreeMatch = content.match(/^##\s+File\s+Tree\s*$/m)
  if (fileTreeMatch?.index !== undefined) {
    const headingEnd = fileTreeMatch.index + fileTreeMatch[0].length
    const afterHeading = content.slice(headingEnd)
    const nextSection = afterHeading.match(/^##\s+\S/m)
    const treeSectionLen = nextSection?.index ?? afterHeading.length
    const treeSection = afterHeading.slice(0, treeSectionLen)
    const treeTrimmed = treeSection.trim()

    if (!treeTrimmed.startsWith("`")) {
      // Remove a trailing lone ``` left by the LLM, then wrap
      const treeText = treeTrimmed.replace(/`{3}\s*$/, "").trim()
      if (looksLikeDirectoryTree(treeText)) {
        const before = content.slice(0, headingEnd)
        const after = afterHeading.slice(treeSectionLen)
        return `${before}\n\n\`\`\`text\n${treeText}\n\`\`\`\n\n${after.trimStart()}`
      }
    }
    return content
  }

  // Pass 2: legacy — bare tree before the first file heading (## or ###)
  const fileHeadingMatch = content.match(/^#{2,3}\s+File:\s+\S/m)
  if (!fileHeadingMatch?.index) return content

  const prefix = content.slice(0, fileHeadingMatch.index).trim()
  const rest = content.slice(fileHeadingMatch.index).trimStart()
  if (!prefix || prefix.startsWith("`")) return content

  const tree = prefix.replace(/`{3}\s*$/, "").trim()
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

// Returns true for "File: path/to/file" but not "File Tree" or "Files".
function isFileHeadingLabel(label: string): boolean {
  return /^file:\s+\S/i.test(label.trim())
}

export function MarkdownRenderer({
  content,
  variant = "default",
}: MarkdownRendererProps) {
  // Harness normalisation must run BEFORE fence repair so that orphaned ```
  // markers from the LLM are removed before normalizeDoubledFences sees them.
  const harnessFixed =
    variant === "harness" ? normalizeHarnessMarkdown(content) : content
  const renderedContent = normalizeDoubledFences(harnessFixed)

  return (
    <RendererErrorBoundary content={content}>
      <div className={variant === "harness" ? "md-prose md-prose-harness" : "md-prose"}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeSanitize, [rehypeHighlight, { ignoreMissing: true }]]}
          components={{
            h2({ children, node: _node, ...props }) {
              const label = textFromChildren(children)
              return (
                <h2
                  {...props}
                  className={isFileHeadingLabel(label) ? "md-file-heading" : undefined}
                >
                  {children}
                </h2>
              )
            },
            h3({ children, node: _node, ...props }) {
              // The harness prompt uses ### File: for per-file headings
              const label = textFromChildren(children)
              return (
                <h3
                  {...props}
                  className={isFileHeadingLabel(label) ? "md-file-heading" : undefined}
                >
                  {children}
                </h3>
              )
            },
            pre({ children, node: _node, ...props }) {
              // Use the language class added by rehype-highlight rather than
              // inspecting text content — more reliable and no false positives.
              // After normalisation, directory trees are always in ```text blocks
              // so they receive class="language-text" on the inner code element.
              const isTree = Children.toArray(children).some(
                (c) =>
                  isValidElement(c) &&
                  String(
                    (c.props as Record<string, unknown>).className ?? ""
                  ).includes("language-text"),
              )
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

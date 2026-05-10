import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"

interface MarkdownRendererProps {
  content: string
  variant?: "default" | "harness"
}

function looksLikeDirectoryTree(value: string): boolean {
  const lines = value
    .split("\n")
    .map((line) => line.trimEnd())
    .filter(Boolean)

  if (lines.length < 2) return false

  return lines.some((line) => /[\u2500-\u257f]/.test(line)) || lines[0].endsWith("/")
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
  const renderedContent =
    variant === "harness" ? normalizeHarnessMarkdown(content) : content

  return (
    <div className={variant === "harness" ? "md-prose md-prose-harness" : "md-prose"}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
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
  )
}

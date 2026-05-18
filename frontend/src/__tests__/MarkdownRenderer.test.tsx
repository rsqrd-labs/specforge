import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  MarkdownRenderer,
  normalizeDoubledFences,
  normalizeHarnessMarkdown,
} from "../components/workspace/MarkdownRenderer"

const harnessContent = `harness/
├── tests/
│   └── unit/
│       └── test_queue.py
└── schemas/
    └── queue.schema.json
\`\`\`

## File: harness/tests/unit/test_queue.py

\`\`\`python
def test_queue_contract():
    assert True
\`\`\``

// ---------------------------------------------------------------------------
// normalizeDoubledFences
// ---------------------------------------------------------------------------

describe("normalizeDoubledFences", () => {
  it("collapses a doubled mermaid opening fence and removes the stray closing fence", () => {
    const input = [
      "## Dependency Graph",
      "```mermaid",
      "```mermaid",
      "graph TD;",
      "  T-001 --> T-002",
      "```",
      "```",
      "",
      "## Task Sizing Legend",
      "- **XS**: tiny tasks",
    ].join("\n")

    const result = normalizeDoubledFences(input)

    // The mermaid block should be intact
    expect(result).toContain("```mermaid\ngraph TD;")
    // The stray ``` must be gone — Task Sizing Legend must not be inside a code block
    // (we verify by checking it appears after the single closing fence)
    const lines = result.split("\n")
    const closingIdx = lines.lastIndexOf("```")
    const legendIdx = lines.findIndex((l) => l.includes("Task Sizing Legend"))
    expect(legendIdx).toBeGreaterThan(closingIdx)
    // Only one closing fence should remain for the mermaid block
    expect(result).not.toContain("```\n```\n")
  })

  it("does not collapse two adjacent legitimate code blocks", () => {
    const input = [
      "```python",
      "code_block_one()",
      "```",
      "```javascript",
      "codeBlockTwo()",
      "```",
    ].join("\n")

    const result = normalizeDoubledFences(input)
    expect(result).toBe(input)
  })

  it("does not alter content with no doubled fences", () => {
    const input = "## Heading\n\nsome paragraph\n\n```bash\necho hello\n```\n\nmore text"
    expect(normalizeDoubledFences(input)).toBe(input)
  })

  it("handles doubled fences with no language identifier", () => {
    const input = ["```", "```", "plain content", "```", "```", "", "after"].join("\n")
    const result = normalizeDoubledFences(input)
    expect(result).toContain("plain content")
    const lines = result.split("\n")
    const afterIdx = lines.indexOf("after")
    const lastFenceIdx = lines.lastIndexOf("```")
    expect(afterIdx).toBeGreaterThan(lastFenceIdx)
  })

  it("closes a fence left open at end of document (truncated generation)", () => {
    // Simulates the LLM being cut off mid-code-block
    const input = [
      "## Section",
      "",
      "Some intro text.",
      "",
      "```python",
      "def foo():",
      "    return 42",
      // no closing ``` — generation was interrupted here
    ].join("\n")

    const result = normalizeDoubledFences(input)

    // The document must end with a closing fence so the content above it
    // renders as normal markdown, not as raw code.
    const lines = result.split("\n").filter((l) => l.trim() !== "")
    expect(lines[lines.length - 1]).toBe("```")
    // The heading must be outside the code block (appears before the fence opens)
    expect(result).toContain("## Section")
  })

  it("leaves a properly closed fence unchanged", () => {
    const input = [
      "## Section",
      "```python",
      "x = 1",
      "```",
      "After block.",
    ].join("\n")
    expect(normalizeDoubledFences(input)).toBe(input)
  })

  it("skips an orphaned closer (bare ``` before a section heading)", () => {
    // A lone ``` with no language before ## heading must not be treated as an opener
    const input = [
      "```text",
      "project/",
      "└── src/",
      "```",
      "```",
      "",
      "## Files",
      "",
      "### File: src/main.py",
      "",
      "```python",
      "print('hello')",
      "```",
    ].join("\n")

    const result = normalizeDoubledFences(input)
    const lines = result.split("\n")

    // "## Files" heading must appear outside any code block
    const filesIdx = lines.findIndex((l) => l === "## Files")
    expect(filesIdx).toBeGreaterThan(-1)
    // "print('hello')" must be inside a code block and visible (not swallowed)
    expect(result).toContain("print('hello')")
    // The orphaned ``` must not introduce an unclosed block — after the final ```
    // there should be no content that was supposed to be prose
    const lastFenceIdx = lines.lastIndexOf("```")
    const fileHeadingIdx = lines.findIndex((l) => l.includes("### File:"))
    expect(fileHeadingIdx).toBeLessThan(lastFenceIdx)
  })

  it("preserves a legitimate bare ``` block that is NOT before a heading", () => {
    // A no-language code block followed by prose (not a heading) must be kept
    const input = [
      "Some text.",
      "",
      "```",
      "plain content here",
      "```",
      "",
      "More prose below.",
    ].join("\n")

    const result = normalizeDoubledFences(input)
    expect(result).toBe(input)
    expect(result).toContain("plain content here")
    expect(result).toContain("More prose below.")
  })
})

// ---------------------------------------------------------------------------
// normalizeHarnessMarkdown
// ---------------------------------------------------------------------------

describe("normalizeHarnessMarkdown", () => {
  it("normalizes harness output with an unfenced leading directory tree (legacy Pass 2)", () => {
    const normalized = normalizeHarnessMarkdown(harnessContent)

    expect(normalized).toContain("## Directory structure")
    expect(normalized).toContain("```text\nharness/")
    expect(normalized).toContain("## File: harness/tests/unit/test_queue.py")
  })

  it("handles Pass 2 with a ### File: three-hash heading", () => {
    const input = [
      "myproject/",
      "├── src/",
      "│   └── app.py",
      "└── tests/",
      "```",
      "",
      "### File: src/app.py",
      "",
      "```python",
      "app = Flask(__name__)",
      "```",
    ].join("\n")

    const result = normalizeHarnessMarkdown(input)

    expect(result).toContain("## Directory structure")
    expect(result).toContain("```text\nmyproject/")
    expect(result).toContain("### File: src/app.py")
    expect(result).toContain("app = Flask(__name__)")
  })

  it("wraps an unfenced tree under ## File Tree section (Pass 1)", () => {
    const input = [
      "## File Tree",
      "",
      "project/",
      "├── src/",
      "│   └── main.py",
      "└── tests/",
      "",
      "## Files",
      "",
      "### File: src/main.py",
      "",
      "```python",
      "x = 1",
      "```",
    ].join("\n")

    const result = normalizeHarnessMarkdown(input)

    expect(result).toContain("## File Tree")
    expect(result).toContain("```text\nproject/")
    expect(result).toContain("## Files")
    expect(result).toContain("### File: src/main.py")
  })

  it("leaves an already-fenced tree under ## File Tree unchanged (Pass 1)", () => {
    const input = [
      "## File Tree",
      "",
      "```text",
      "project/",
      "└── main.py",
      "```",
      "",
      "## Files",
      "",
      "### File: main.py",
      "",
      "```python",
      "pass",
      "```",
    ].join("\n")

    const result = normalizeHarnessMarkdown(input)

    // Already fenced — must not double-wrap
    expect(result).toBe(input)
  })

  it("leaves content unchanged when there is no bare tree and no File Tree heading", () => {
    const input = "## Introduction\n\nSome text.\n\n```python\nx = 1\n```\n"
    expect(normalizeHarnessMarkdown(input)).toBe(input)
  })
})

// ---------------------------------------------------------------------------
// Integration: execution order (harness normalisation before fence repair)
// ---------------------------------------------------------------------------

describe("MarkdownRenderer integration: execution order", () => {
  it("renders harness content with bare tree + orphaned closer without swallowing file blocks", () => {
    // The orphaned ``` after the bare tree must be removed by normalizeHarnessMarkdown
    // BEFORE normalizeDoubledFences sees it. If order is wrong, the ``` opens an
    // unclosed block and swallows everything after it.
    const input = [
      "project/",
      "├── src/",
      "│   └── index.ts",
      "└── package.json",
      "```",
      "",
      "### File: src/index.ts",
      "",
      "```typescript",
      "export const x = 1",
      "```",
    ].join("\n")

    const { container } = render(
      <MarkdownRenderer content={input} variant="harness" />,
    )

    // File heading must be rendered as a heading, not swallowed into a code block
    expect(screen.getByRole("heading", { name: /src\/index\.ts/i })).toBeInTheDocument()
    // Code content must be visible
    expect(container.textContent).toContain("export const x = 1")
  })
})

// ---------------------------------------------------------------------------
// MarkdownRenderer component
// ---------------------------------------------------------------------------

describe("MarkdownRenderer", () => {
  it("normalizes harness output with an unfenced leading directory tree", () => {
    const normalized = normalizeHarnessMarkdown(harnessContent)

    expect(normalized).toContain("## Directory structure")
    expect(normalized).toContain("```text\nharness/")
    expect(normalized).toContain("## File: harness/tests/unit/test_queue.py")
  })

  it("renders harness directory trees and file blocks as code", () => {
    const { container } = render(
      <MarkdownRenderer content={harnessContent} variant="harness" />,
    )

    expect(screen.getByRole("heading", { name: /directory structure/i })).toBeInTheDocument()
    expect(screen.getAllByText(/test_queue.py/).length).toBeGreaterThan(0)
    expect(container.textContent).toContain("def test_queue_contract")
    expect(container.querySelector(".md-directory-tree")).toBeInTheDocument()
    expect(container.querySelector(".md-file-heading")).toBeInTheDocument()
  })

  it("applies md-file-heading class to h3 ### File: headings", () => {
    const input = [
      "### File: src/app.py",
      "",
      "```python",
      "pass",
      "```",
    ].join("\n")

    const { container } = render(
      <MarkdownRenderer content={input} variant="harness" />,
    )

    const h3 = container.querySelector("h3.md-file-heading")
    expect(h3).toBeInTheDocument()
    expect(h3?.textContent).toMatch(/src\/app\.py/)
  })

  it("does NOT apply md-file-heading class to ## Files or ## File Tree headings", () => {
    const input = [
      "## Files",
      "",
      "## File Tree",
      "",
      "```text",
      "project/",
      "└── src/",
      "```",
    ].join("\n")

    const { container } = render(
      <MarkdownRenderer content={input} variant="harness" />,
    )

    // Neither "Files" nor "File Tree" headings should get the file-heading card style
    const fileHeadings = container.querySelectorAll(".md-file-heading")
    for (const el of Array.from(fileHeadings)) {
      expect(el.textContent).not.toMatch(/^Files$/)
      expect(el.textContent).not.toMatch(/^File Tree$/)
    }
  })

  it("applies md-directory-tree class to pre wrapping a ```text block", () => {
    // normalizeHarnessMarkdown wraps bare trees in ```text; the pre component
    // detects language-text class from rehype-highlight and adds md-directory-tree.
    const input = [
      "project/",
      "├── src/",
      "│   └── main.py",
      "└── tests/",
      "```",
      "",
      "### File: src/main.py",
      "",
      "```python",
      "x = 1",
      "```",
    ].join("\n")

    const { container } = render(
      <MarkdownRenderer content={input} variant="harness" />,
    )

    expect(container.querySelector("pre.md-directory-tree")).toBeInTheDocument()
  })

  it("does NOT apply md-directory-tree to non-tree code blocks", () => {
    const input = "```python\ndef foo():\n    return 42\n```"

    const { container } = render(
      <MarkdownRenderer content={input} variant="default" />,
    )

    expect(container.querySelector("pre.md-directory-tree")).not.toBeInTheDocument()
    expect(container.querySelector("pre")).toBeInTheDocument()
  })
})

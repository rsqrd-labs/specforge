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
})

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
})

import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  MarkdownRenderer,
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

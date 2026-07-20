/**
 * Harness contracts for T-093: Focus trap and ARIA semantics for all three modals.
 * RED before T-093 is implemented (no useFocusTrap, no ARIA attributes on modals).
 * GREEN after useFocusTrap.ts is created and all three modals apply it.
 */
import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { resolve, dirname } from "node:path"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")
const FRONTEND_SRC = resolve(REPO_ROOT, "frontend/src")

// -----------------------------------------------------------------------
// Source-level contracts (RED until files exist / contain the right code)
// -----------------------------------------------------------------------

describe("T-093: useFocusTrap hook", () => {
  it("useFocusTrap.ts exists at frontend/src/hooks/useFocusTrap.ts", () => {
    const hookPath = resolve(FRONTEND_SRC, "hooks/useFocusTrap.ts")
    expect(existsSync(hookPath)).toBe(true)
  })

  it("useFocusTrap exports a useFocusTrap function", () => {
    const hookPath = resolve(FRONTEND_SRC, "hooks/useFocusTrap.ts")
    const source = readFileSync(hookPath, "utf-8")
    expect(source).toContain("export function useFocusTrap")
  })

  it("useFocusTrap handles Escape key by calling onClose", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "hooks/useFocusTrap.ts"),
      "utf-8",
    )
    expect(source).toContain('"Escape"')
    expect(source).toContain("onClose")
  })

  it("useFocusTrap handles Tab key to cycle focus within the dialog", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "hooks/useFocusTrap.ts"),
      "utf-8",
    )
    expect(source).toContain('"Tab"')
    expect(source).toContain("shiftKey")
  })

  it("useFocusTrap defines FOCUSABLE selector covering button, input, a[href]", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "hooks/useFocusTrap.ts"),
      "utf-8",
    )
    expect(source).toContain("button")
    expect(source).toContain("input")
    expect(source).toContain("a[href]")
  })

  it("useFocusTrap focuses the first focusable element on mount", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "hooks/useFocusTrap.ts"),
      "utf-8",
    )
    expect(source).toContain("focusable[0]")
    expect(source).toMatch(/initial\??\.focus\(\)/)
  })
})

describe("T-093: CreditConfirmModal ARIA semantics", () => {
  it("CreditConfirmModal.tsx imports useFocusTrap", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/workspace/CreditConfirmModal.tsx"),
      "utf-8",
    )
    expect(source).toContain("useFocusTrap")
  })

  it("CreditConfirmModal.tsx has role='dialog' on the dialog container", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/workspace/CreditConfirmModal.tsx"),
      "utf-8",
    )
    expect(source).toContain('role="dialog"')
  })

  it("CreditConfirmModal.tsx has aria-modal='true'", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/workspace/CreditConfirmModal.tsx"),
      "utf-8",
    )
    expect(source).toContain('aria-modal="true"')
  })

  it("CreditConfirmModal.tsx has aria-labelledby pointing to its title", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/workspace/CreditConfirmModal.tsx"),
      "utf-8",
    )
    expect(source).toContain("aria-labelledby")
    expect(source).toContain("credit-modal-title")
  })

  it("CreditConfirmModal.tsx h2 has id='credit-modal-title'", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/workspace/CreditConfirmModal.tsx"),
      "utf-8",
    )
    expect(source).toContain('id="credit-modal-title"')
  })
})

describe("T-093: HumanReviewGate ARIA semantics", () => {
  it("HumanReviewGate.tsx imports useFocusTrap", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/workspace/HumanReviewGate.tsx"),
      "utf-8",
    )
    expect(source).toContain("useFocusTrap")
  })

  it("HumanReviewGate.tsx has role='dialog' on the dialog container", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/workspace/HumanReviewGate.tsx"),
      "utf-8",
    )
    expect(source).toContain('role="dialog"')
  })

  it("HumanReviewGate.tsx has aria-modal='true'", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/workspace/HumanReviewGate.tsx"),
      "utf-8",
    )
    expect(source).toContain('aria-modal="true"')
  })

  it("HumanReviewGate.tsx has aria-labelledby pointing to review-gate-title", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/workspace/HumanReviewGate.tsx"),
      "utf-8",
    )
    expect(source).toContain("aria-labelledby")
    expect(source).toContain("review-gate-title")
  })
})

describe("T-093: CreateWorkspaceModal ARIA semantics", () => {
  it("CreateWorkspaceModal.tsx imports useFocusTrap", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/dashboard/CreateWorkspaceModal.tsx"),
      "utf-8",
    )
    expect(source).toContain("useFocusTrap")
  })

  it("CreateWorkspaceModal.tsx has role='dialog' on the dialog container", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/dashboard/CreateWorkspaceModal.tsx"),
      "utf-8",
    )
    expect(source).toContain('role="dialog"')
  })

  it("CreateWorkspaceModal.tsx has aria-modal='true'", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/dashboard/CreateWorkspaceModal.tsx"),
      "utf-8",
    )
    expect(source).toContain('aria-modal="true"')
  })

  it("CreateWorkspaceModal.tsx has aria-labelledby pointing to create-workspace-title", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "components/dashboard/CreateWorkspaceModal.tsx"),
      "utf-8",
    )
    expect(source).toContain("aria-labelledby")
    expect(source).toContain("create-workspace-title")
  })
})

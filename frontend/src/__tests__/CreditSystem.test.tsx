import type { ComponentProps } from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import { CreditBanner } from "../components/dashboard/CreditBanner"
import { CreditMeter } from "../components/shared/CreditMeter"
import { CreditConfirmModal } from "../components/workspace/CreditConfirmModal"

describe("CreditMeter", () => {
  function renderCreditMeter(balance: number) {
    return render(
      <MemoryRouter>
        <CreditMeter balance={balance} />
      </MemoryRouter>,
    )
  }

  it("shows 'used all credits' message when balance is 0", () => {
    renderCreditMeter(0)
    expect(screen.getByText(/you're at 0 credits/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /buy more credits/i })).toHaveAttribute(
      "href",
      "/billing",
    )
  })

  it("shows remaining count when balance is positive", () => {
    renderCreditMeter(25)
    expect(screen.getByText("25")).toBeInTheDocument()
    expect(screen.getByText(/credits remaining/i)).toBeInTheDocument()
  })

  it("applies error text class when balance is 0", () => {
    const { container } = renderCreditMeter(0)
    expect(container.firstChild).toHaveClass("text-error")
  })
})

describe("CreditBanner", () => {
  function renderCreditBanner(balance: number) {
    return render(
      <MemoryRouter>
        <CreditBanner balance={balance} />
      </MemoryRouter>,
    )
  }

  it("applies error-soft class when balance is at low threshold (≤5)", () => {
    const { container } = renderCreditBanner(5)
    expect(container.firstChild).toHaveClass("bg-status-error-soft")
  })

  it("applies error-soft class when balance is 0", () => {
    const { container } = renderCreditBanner(0)
    expect(container.firstChild).toHaveClass("bg-status-error-soft")
  })

  it("does not apply error-soft class when balance is above threshold", () => {
    const { container } = renderCreditBanner(6)
    expect(container.firstChild).not.toHaveClass("bg-status-error-soft")
  })
})

describe("CreditConfirmModal", () => {
  const defaults = {
    action: "generate" as const,
    creditCost: 10,
    currentBalance: 30,
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  }

  // The out-of-credits state renders a router <Link> to billing, so every
  // case is wrapped in a MemoryRouter to supply the routing context.
  function renderModal(
    props: Partial<ComponentProps<typeof CreditConfirmModal>> = {},
  ) {
    return render(
      <MemoryRouter>
        <CreditConfirmModal {...defaults} {...props} />
      </MemoryRouter>,
    )
  }

  it("displays the credit cost and current balance", () => {
    renderModal()
    expect(screen.getByText("10")).toBeInTheDocument()
    expect(screen.getByText("30")).toBeInTheDocument()
  })

  it("shows the action name capitalised in the heading", () => {
    renderModal({ action: "regenerate" })
    expect(
      screen.getByRole("heading", { name: /^regenerate$/i }),
    ).toBeInTheDocument()
  })

  it("describes the selected action as value instead of token details", () => {
    renderModal({ action: "refine", creditCost: 3 })
    expect(
      screen.getByRole("heading", { name: /^refine$/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(/preview a precise edit/i)).toBeInTheDocument()
    expect(screen.queryByText(/token/i)).not.toBeInTheDocument()
  })

  it("calls onConfirm when the action button is clicked", async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    renderModal({ onConfirm })
    await user.click(screen.getByRole("button", { name: /^generate$/i }))
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it("calls onCancel when Cancel button is clicked", async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    renderModal({ onCancel })
    await user.click(screen.getByRole("button", { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  describe("when the balance is insufficient", () => {
    const broke = { currentBalance: 0 }

    it("shows an out-of-credits card instead of a negative balance", () => {
      renderModal(broke)
      expect(
        screen.getByRole("heading", { name: /out of credits/i }),
      ).toBeInTheDocument()
      // No negative "After" figure and no confirm/generate action.
      expect(screen.queryByText("-10")).not.toBeInTheDocument()
      expect(
        screen.queryByRole("button", { name: /^generate$/i }),
      ).not.toBeInTheDocument()
    })

    it("offers a billing link to buy more credits", () => {
      renderModal(broke)
      expect(
        screen.getByRole("link", { name: /buy credits/i }),
      ).toHaveAttribute("href", "/billing")
    })

    it("dismisses when the billing link is followed", async () => {
      const user = userEvent.setup()
      const onCancel = vi.fn()
      renderModal({ ...broke, onCancel })
      await user.click(screen.getByRole("link", { name: /buy credits/i }))
      expect(onCancel).toHaveBeenCalledOnce()
    })
  })
})

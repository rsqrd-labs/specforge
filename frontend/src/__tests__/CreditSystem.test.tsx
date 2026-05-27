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

  it("applies error-container class when balance is at low threshold (≤5)", () => {
    const { container } = renderCreditBanner(5)
    expect(container.firstChild).toHaveClass("bg-error-container")
  })

  it("applies error-container class when balance is 0", () => {
    const { container } = renderCreditBanner(0)
    expect(container.firstChild).toHaveClass("bg-error-container")
  })

  it("does not apply error-container class when balance is above threshold", () => {
    const { container } = renderCreditBanner(6)
    expect(container.firstChild).not.toHaveClass("bg-error-container")
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

  it("displays the credit cost and current balance", () => {
    render(<CreditConfirmModal {...defaults} />)
    expect(screen.getByText("10")).toBeInTheDocument()
    expect(screen.getByText("30")).toBeInTheDocument()
  })

  it("shows the action name capitalised in the heading", () => {
    render(<CreditConfirmModal {...defaults} action="regenerate" />)
    expect(
      screen.getByRole("heading", { name: /full stage regenerate/i }),
    ).toBeInTheDocument()
  })

  it("describes the selected action as value instead of token details", () => {
    render(<CreditConfirmModal {...defaults} action="refine" creditCost={3} />)
    expect(
      screen.getByRole("heading", { name: /focused patch/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(/preview a focused patch/i)).toBeInTheDocument()
    expect(screen.queryByText(/token/i)).not.toBeInTheDocument()
  })

  it("calls onConfirm when Confirm button is clicked", async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(<CreditConfirmModal {...defaults} onConfirm={onConfirm} />)
    await user.click(screen.getByRole("button", { name: /confirm/i }))
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it("calls onCancel when Cancel button is clicked", async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    render(<CreditConfirmModal {...defaults} onCancel={onCancel} />)
    await user.click(screen.getByRole("button", { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalledOnce()
  })
})

import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import Billing from "../pages/Billing"
import { AI_DISCLAIMER_COPY } from "../components/shared/AiDisclaimer"
import {
  createCheckoutSession,
  fetchBillingHistory,
  fetchBillingPackage,
  fetchBillingStatus,
  getCredits,
} from "../services/api"
import type { BillingCreditPack, BillingPackage } from "../types/billing"

vi.mock("../services/api", () => ({
  createCheckoutSession: vi.fn(),
  fetchBillingHistory: vi.fn(),
  fetchBillingPackage: vi.fn(),
  fetchBillingStatus: vi.fn(),
  getApiErrorMessage: (_error: unknown, fallback: string) => fallback,
  getCredits: vi.fn(),
}))

const mockCreateCheckout = vi.mocked(createCheckoutSession)
const mockHistory = vi.mocked(fetchBillingHistory)
const mockPackage = vi.mocked(fetchBillingPackage)
const mockStatus = vi.mocked(fetchBillingStatus)
const mockCredits = vi.mocked(getCredits)

const PACKAGE: BillingPackage = {
  credits: 200,
  price_cents: 900,
  validity_days: 30,
  currency: "USD",
}

function pack(overrides: Partial<BillingCreditPack>): BillingCreditPack {
  return {
    id: "pack-1",
    credits_purchased: 200,
    credits_remaining: 200,
    price_cents: 900,
    status: "active",
    purchased_at: "2026-01-01T00:00:00Z",
    expires_at: "2026-02-01T00:00:00Z",
    ...overrides,
  }
}

function balance(over: Partial<Awaited<ReturnType<typeof getCredits>>> = {}) {
  return { balance: 200, generation_cost: 10, billing_debt_credits: 0, ...over }
}

function renderBilling(path = "/billing") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Billing />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockPackage.mockResolvedValue(PACKAGE)
  mockHistory.mockResolvedValue([])
  mockCredits.mockResolvedValue(balance())
  mockStatus.mockResolvedValue(null)
  mockCreateCheckout.mockResolvedValue({
    checkout_url: "https://pay.lemonsqueezy.com/x",
    checkout_ref: "ref-1",
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("Billing — history rendering", () => {
  it("renders BillingCreditPack rows with a calm 'Refunded' chip and no Stripe copy", async () => {
    mockHistory.mockResolvedValue([
      pack({ id: "p-active", status: "active" }),
      pack({ id: "p-refunded", status: "refunded", credits_remaining: 0 }),
    ])

    const { container } = renderBilling()

    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument())
    expect(screen.getByText("Refunded")).toBeInTheDocument()
    // The refunded chip is the calm slate variant, never the red error chip.
    const refundedChip = container.querySelector(".billing-status-chip.refunded")
    expect(refundedChip).not.toBeNull()
    expect(container.textContent).not.toMatch(/Stripe/)
    expect(screen.getByText(AI_DISCLAIMER_COPY)).toBeInTheDocument()
  })
})

describe("Billing — checkout_ref polling", () => {
  it("polls by checkout_ref and resolves to the credits-added confirmation", async () => {
    mockStatus.mockResolvedValue({
      status: "completed",
      credits_added: 200,
      expires_at: "2026-02-01T00:00:00Z",
    })

    renderBilling("/billing?checkout_ref=ref-1")

    await waitFor(() =>
      expect(mockStatus).toHaveBeenCalledWith("ref-1"),
    )
    await waitFor(() =>
      expect(screen.getByText(/200 credits added/i)).toBeInTheDocument(),
    )
  })

  it("shows the calm settling state while the grant is still pending (404)", async () => {
    mockStatus.mockResolvedValue(null) // 404 → pending, not an error

    renderBilling("/billing?checkout_ref=ref-pending")

    await waitFor(() =>
      expect(screen.getByText(/adding your credits/i)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/unable to verify/i)).not.toBeInTheDocument()
  })

  it("surfaces a real error distinctly from a pending 404", async () => {
    mockStatus.mockRejectedValue(new Error("boom"))

    renderBilling("/billing?checkout_ref=ref-err")

    await waitFor(() =>
      expect(screen.getByText(/unable to verify payment status/i)).toBeInTheDocument(),
    )
  })
})

describe("Billing — payment-reversal debt", () => {
  it("shows debt as a distinct note and never folds it into the usable balance", async () => {
    mockCredits.mockResolvedValue(balance({ balance: 200, billing_debt_credits: 50 }))

    const { container } = renderBilling()

    await waitFor(() =>
      expect(screen.getByText(/reversed payment/i)).toBeInTheDocument(),
    )
    // The note is role=note (informational), never a red alert.
    const note = container.querySelector(".billing-debt-note")
    expect(note).not.toBeNull()
    expect(note?.getAttribute("role")).toBe("note")
    // The usable balance shows 200 — NOT 250 (200 + 50 debt).
    const balanceValue = container.querySelector(".billing-balance-value")
    expect(balanceValue?.textContent).toBe("200")
  })

  it("renders no debt note when there is no pending reversal debt", async () => {
    mockCredits.mockResolvedValue(balance({ billing_debt_credits: 0 }))

    const { container } = renderBilling()

    await waitFor(() => expect(screen.getByText("200")).toBeInTheDocument())
    expect(container.querySelector(".billing-debt-note")).toBeNull()
  })
})

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
  enabled: true,
  provider: "lemonsqueezy",
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
    expect(container.querySelector(".billing-nav-brand .brand-logo-image")).not.toBeNull()
    expect(container.textContent).not.toMatch(/Stripe/)
    expect(container.textContent).not.toMatch(/\bSF\b/)
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
      expect(screen.getByText(/payment status could not be verified/i)).toBeInTheDocument(),
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

describe("Billing — checkout availability gate (issue #44)", () => {
  it("hides Buy, keeps the package card, and shows the quiet slate note when disabled", async () => {
    mockPackage.mockResolvedValue({ ...PACKAGE, enabled: false })

    const { container } = renderBilling()

    // The package economics still render — only the button is swapped out.
    await waitFor(() =>
      expect(screen.getByText("200 credits")).toBeInTheDocument(),
    )
    expect(container.querySelector(".billing-package-card")).not.toBeNull()
    expect(screen.getByText(/30-day validity/)).toBeInTheDocument()

    // No Buy button; a calm role=note note in its place (coherent when arriving
    // from an out-of-credits alert).
    expect(
      screen.queryByRole("button", { name: /buy credits/i }),
    ).not.toBeInTheDocument()
    const note = container.querySelector(".billing-unavailable-note")
    expect(note).not.toBeNull()
    expect(note?.getAttribute("role")).toBe("note")
    expect(note?.textContent).toMatch(/aren't available yet/i)
  })

  it("shows the Buy button when checkout is enabled", async () => {
    mockPackage.mockResolvedValue({ ...PACKAGE, enabled: true })

    const { container } = renderBilling()

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /buy credits/i })).toBeInTheDocument(),
    )
    expect(container.querySelector(".billing-unavailable-note")).toBeNull()
  })

  it("still polls a returning ?checkout_ref to completion while disabled (kill switch mid-flight)", async () => {
    // PAYMENTS_ENABLED flipped false after a user started checkout — the webhook
    // still grants (D3) and PaymentStatusPanel must poll regardless of `enabled`.
    mockPackage.mockResolvedValue({ ...PACKAGE, enabled: false })
    mockStatus.mockResolvedValue({
      status: "completed",
      credits_added: 200,
      expires_at: "2026-02-01T00:00:00Z",
    })

    renderBilling("/billing?checkout_ref=ref-inflight")

    await waitFor(() =>
      expect(mockStatus).toHaveBeenCalledWith("ref-inflight"),
    )
    await waitFor(() =>
      expect(screen.getByText(/200 credits added/i)).toBeInTheDocument(),
    )
  })
})

describe("Billing — currency formatting (issue #44)", () => {
  it("renders INR as ₹ via the Intl path", async () => {
    mockPackage.mockResolvedValue({
      ...PACKAGE,
      price_cents: 79900,
      currency: "INR",
    })

    const { container } = renderBilling()

    await waitFor(() =>
      expect(container.querySelector(".billing-package-price")).not.toBeNull(),
    )
    const price = container.querySelector(".billing-package-price")?.textContent ?? ""
    // Intl renders INR with the ₹ symbol; never a "$" fallback.
    expect(price).toMatch(/₹\s?799/)
    expect(price).not.toMatch(/\$/)
  })

  it("falls back to the currency code, not '$', when Intl cannot format it", async () => {
    // Force the catch branch: a malformed (non-3-letter) code makes
    // Intl.NumberFormat throw RangeError. The fallback must prefix the code, not "$".
    mockPackage.mockResolvedValue({
      ...PACKAGE,
      price_cents: 79900,
      currency: "INRX",
    })

    const { container } = renderBilling()

    await waitFor(() =>
      expect(container.querySelector(".billing-package-price")).not.toBeNull(),
    )
    const price = container.querySelector(".billing-package-price")?.textContent ?? ""
    expect(price).toMatch(/INRX\s?799/)
    expect(price).not.toMatch(/\$/)
  })
})

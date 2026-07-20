import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { BillingCreditPack } from "../../types/billing"
import { CreditMeter } from "./CreditMeter"

const navigate = vi.fn()
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}))

const pack = (days: number, overrides: Partial<BillingCreditPack> = {}): BillingCreditPack => {
  const expires = new Date()
  expires.setHours(12, 0, 0, 0)
  expires.setDate(expires.getDate() + days)
  return {
    id: `pack-${days}`, credits_purchased: 50, credits_remaining: 12,
    price_cents: 500, currency: "USD", status: "active",
    purchased_at: new Date().toISOString(), expires_at: expires.toISOString(), ...overrides,
  }
}

describe("CreditMeter", () => {
  beforeEach(() => navigate.mockReset())
  afterEach(() => vi.useRealTimers())

  it("links zero balances to billing", () => {
    render(<MemoryRouter><CreditMeter balance={0} variant="inverse" /></MemoryRouter>)
    expect(screen.getByRole("link", { name: /buy more credits/i })).toHaveAttribute("href", "/billing")
  })

  it.each([
    [0, "today", "urgent"],
    [1, "tomorrow", "urgent"],
    [3, "in 3 days", "urgent"],
    [6, null, "amber"],
  ] as const)("surfaces expiry at %s days", (days, label, tone) => {
    render(<MemoryRouter><CreditMeter balance={20} packs={[pack(days)]} /></MemoryRouter>)
    const button = screen.getByRole("button", { name: /credits expire/i })
    if (label) expect(button).toHaveTextContent(label)
    expect(button).toHaveClass(tone)
    fireEvent.click(button)
    expect(navigate).toHaveBeenCalledWith("/billing")
  })

  it("ignores invalid, exhausted, expired, and distant packs", () => {
    render(<MemoryRouter><CreditMeter balance={20} packs={[
      pack(2, { status: "consumed" }), pack(2, { credits_remaining: 0 }),
      pack(-1), pack(20), pack(2, { expires_at: "invalid" }),
    ]} /></MemoryRouter>)
    expect(screen.queryByRole("button", { name: /credits expire/i })).not.toBeInTheDocument()
  })

  it("omits redundant inverse balance copy without an expiry", () => {
    const { container } = render(<MemoryRouter><CreditMeter balance={20} variant="inverse" /></MemoryRouter>)
    expect(container).toBeEmptyDOMElement()
  })
})

/**
 * Harness contracts for Plan v1.md §25, Phase 25 — Lemon Squeezy Billing
 * Migration (frontend layer: T-305 plus the api/type contracts for checkout_ref
 * polling and the payment-reversal debt display).
 *
 * These tests are RED before the frontend work lands and GREEN after. They are
 * the client-side verifiability layer for the coding agent. They encode the
 * plan, not the old Stripe behaviour.
 *
 * Invariants:
 *   - types/billing.ts renames StripeCreditPack → BillingCreditPack (status union
 *     includes 'refunded'), CheckoutResponse carries checkout_ref, and the
 *     package type carries currency.
 *   - The Billing page redirects to checkout_url and polls GET /billing/status by
 *     checkout_ref (not session_id), and reads history as BillingCreditPack.
 *   - billing_debt_credits is surfaced as payment-reversal debt, visually distinct,
 *     and never folded into the usable balance.
 *   - No visible "Stripe" copy remains in the billing UI.
 */

import { describe, expect, it } from "vitest"
import { readFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")

async function tryRead(relPath: string): Promise<string | null> {
  try {
    return await readFile(resolve(REPO_ROOT, relPath), "utf8")
  } catch {
    return null
  }
}

/** Read the first frontend file that exists from a list of candidates. */
async function tryReadAny(
  relPaths: string[],
): Promise<{ path: string; src: string } | null> {
  for (const p of relPaths) {
    const src = await tryRead(p)
    if (src !== null) return { path: p, src }
  }
  return null
}

function expectContainsAll(source: string, required: string[], context: string) {
  const missing = required.filter((term) => !source.includes(term))
  expect(missing, `${context} missing required terms: ${missing.join(", ")}`).toEqual([])
}

function expectContainsAny(source: string, options: string[], context: string) {
  expect(
    options.some((o) => source.includes(o)),
    `${context} must include one of: ${options.join(", ")}`,
  ).toBe(true)
}

const BILLING_TYPE_CANDIDATES = [
  "frontend/src/types/billing.ts",
  "frontend/src/types/billing.d.ts",
]
const BILLING_PAGE_CANDIDATES = [
  "frontend/src/pages/Billing.tsx",
  "frontend/src/pages/billing/Billing.tsx",
]
const API_CANDIDATES = ["frontend/src/services/api.ts"]
const BALANCE_UI_CANDIDATES = [
  "frontend/src/components/shared/CreditMeter.tsx",
  "frontend/src/components/workspace/QualityBadge.tsx", // unlikely; falls through
  "frontend/src/pages/Billing.tsx",
]

describe("phase25 types/billing.ts — provider-neutral billing types", () => {
  it("renames StripeCreditPack → BillingCreditPack with a 'refunded' status", async () => {
    const found = await tryReadAny(BILLING_TYPE_CANDIDATES)
    expect(found, "frontend/src/types/billing.ts must exist (T-305)").not.toBeNull()
    const src = found!.src
    expect(
      src.includes("BillingCreditPack"),
      "types/billing.ts must export BillingCreditPack (renamed from StripeCreditPack). T-305.",
    ).toBe(true)
    expectContainsAll(
      src,
      ["active", "consumed", "expired", "refunded"],
      "BillingCreditPack status union (must include 'refunded')",
    )
  })

  it("CheckoutResponse carries checkout_ref and the package carries currency", async () => {
    const found = await tryReadAny(BILLING_TYPE_CANDIDATES)
    expect(found).not.toBeNull()
    const src = found!.src
    expect(
      src.includes("checkout_ref"),
      "CheckoutResponse must include checkout_ref (the poll key). T-305.",
    ).toBe(true)
    expect(
      src.includes("currency"),
      "The billing package type must include currency. T-305.",
    ).toBe(true)
  })

  it("does not keep a StripeCreditPack type name", async () => {
    const found = await tryReadAny(BILLING_TYPE_CANDIDATES)
    expect(found).not.toBeNull()
    expect(
      /interface\s+StripeCreditPack|type\s+StripeCreditPack/.test(found!.src),
      "types/billing.ts must not keep the StripeCreditPack type — rename it to BillingCreditPack. T-305.",
    ).toBe(false)
  })
})

describe("phase25 Billing page — checkout_ref polling", () => {
  it("polls GET /billing/status by checkout_ref, not session_id", async () => {
    const page = await tryReadAny(BILLING_PAGE_CANDIDATES)
    const api = await tryReadAny(API_CANDIDATES)
    const combined = `${page?.src ?? ""}\n${api?.src ?? ""}`
    expect(
      combined.length > 0,
      "Billing.tsx (and/or api.ts) must exist. T-305.",
    ).toBe(true)
    expect(
      combined.includes("checkout_ref"),
      "The billing flow must poll /billing/status by checkout_ref. T-305.",
    ).toBe(true)
    expectContainsAny(
      combined,
      ["/billing/status", "billing/status"],
      "The billing flow must call the /billing/status endpoint",
    )
  })

  it("redirects to the provider checkout_url returned by /billing/checkout", async () => {
    const page = await tryReadAny(BILLING_PAGE_CANDIDATES)
    const api = await tryReadAny(API_CANDIDATES)
    const combined = `${page?.src ?? ""}\n${api?.src ?? ""}`
    expect(
      combined.includes("checkout_url"),
      "The billing flow must redirect to the checkout_url from POST /billing/checkout. T-305.",
    ).toBe(true)
  })
})

describe("phase25 payment-reversal debt", () => {
  it("surfaces billing_debt_credits as debt, distinct from usable balance", async () => {
    const found = await tryReadAny([...BALANCE_UI_CANDIDATES, ...BILLING_PAGE_CANDIDATES])
    expect(found, "a billing/balance UI file must exist").not.toBeNull()
    // The token must appear somewhere in the billing/balance UI surface.
    const anySurface = (
      (await tryRead("frontend/src/pages/Billing.tsx")) ?? ""
    ) + (
      (await tryRead("frontend/src/components/shared/CreditMeter.tsx")) ?? ""
    ) + (
      (await tryRead("frontend/src/services/api.ts")) ?? ""
    ) + (
      (await tryRead("frontend/src/types/billing.ts")) ?? ""
    ) + (
      (await tryRead("frontend/src/types/credits.ts")) ?? ""
    )
    expect(
      anySurface.includes("billing_debt_credits"),
      "The UI must read billing_debt_credits and render it as payment-reversal debt, " +
        "never folded into the usable balance. T-305 / §11.",
    ).toBe(true)
  })
})

describe("phase25 no visible Stripe copy", () => {
  it("the Billing page shows no user-facing 'Stripe' wording", async () => {
    const page = await tryReadAny(BILLING_PAGE_CANDIDATES)
    expect(page, "Billing.tsx must exist").not.toBeNull()
    // Allow code identifiers that may legitimately survive (none expected), but
    // forbid the visible brand word in the page copy.
    expect(
      /Stripe/.test(page!.src),
      "Billing.tsx must not contain visible 'Stripe' copy — use neutral / Lemon " +
        "Squeezy language. T-305.",
    ).toBe(false)
  })
})

/*
Visual hierarchy: current balance first (with any payment-reversal debt shown as a
quiet, distinct slate note beside it — never folded into the usable figure), the
single credit pack offer second, and purchase history third. Tiny delight: the
brand mark pulses while we settle the checkout, and the balance figure gives a gentle
saffron tick-up when new credits land.
*/
import { useCallback, useEffect, useMemo, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"

import { AiDisclaimer } from "../components/shared/AiDisclaimer"
import { BrandLogo } from "../components/shared/BrandLogo"
import {
  createCheckoutSession,
  fetchBillingHistory,
  fetchBillingPackage,
  fetchBillingStatus,
  getApiErrorMessage,
  getCredits,
} from "../services/api"
import type { BillingCreditPack, BillingPackage } from "../types/billing"

type LoadState = "loading" | "ready" | "error"
type PollingStatus = "idle" | "processing" | "completed" | "timeout" | "error"

const statusLabels: Record<BillingCreditPack["status"], string> = {
  active: "Active",
  consumed: "Consumed",
  expired: "Expired",
  refunded: "Refunded",
  disputed: "Refunded",
}

function formatDate(value: string | null | undefined, withYear = true): string {
  if (!value) return "pending"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "pending"
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    ...(withYear ? { year: "numeric" as const } : {}),
  }).format(date)
}

function formatPrice(priceCents: number, currency: string): string {
  const normalizedCurrency = (currency || "usd").toUpperCase()
  try {
    return (priceCents / 100).toLocaleString("en-US", {
      style: "currency",
      currency: normalizedCurrency,
      maximumFractionDigits: 0,
    })
  } catch {
    return `$${(priceCents / 100).toFixed(0)}`
  }
}

function activePackSummary(packs: BillingCreditPack[]): string | null {
  const activePacks = packs.filter(
    (pack) => pack.status === "active" && pack.credits_remaining > 0,
  )
  if (activePacks.length === 0) return null

  const activeCredits = activePacks.reduce(
    (total, pack) => total + pack.credits_remaining,
    0,
  )
  const soonest = [...activePacks].sort(
    (a, b) => new Date(a.expires_at).getTime() - new Date(b.expires_at).getTime(),
  )[0]

  return `${activeCredits} active · expires ${formatDate(soonest.expires_at, false)}`
}

function BillingNav() {
  return (
    <nav className="billing-nav">
      <div className="billing-nav-inner">
        <Link to="/dashboard" className="billing-nav-back" aria-label="Back to Dashboard">
          <span aria-hidden="true">←</span>
          Dashboard
        </Link>
        <div className="billing-nav-brand">
          <BrandLogo size="small" decorative />
          <span className="settings-nav-divider">/</span>
          <span className="settings-nav-section">Billing</span>
        </div>
        <span className="billing-nav-spacer">spacer</span>
      </div>
    </nav>
  )
}

interface PaymentStatusPanelProps {
  status: PollingStatus
  creditsAdded: number | null
  expiresAt: string | null
}

function PaymentStatusPanel({
  status,
  creditsAdded,
  expiresAt,
}: PaymentStatusPanelProps) {
  if (status === "idle") return null

  return (
    <section className={`billing-payment-status ${status}`} aria-live="polite">
      <div className="billing-payment-mark" aria-hidden="true">
        <BrandLogo size="small" decorative />
      </div>
      {status === "processing" && (
        <>
          <h1>Adding your credits…</h1>
          <p>This usually takes a few seconds.</p>
        </>
      )}
      {status === "completed" && (
        <>
          <h1>
            {creditsAdded ?? 0} credits added · expires {formatDate(expiresAt)}
          </h1>
          <p>Your balance has been refreshed.</p>
          <Link to="/dashboard" className="billing-status-link">
            Continue to Dashboard →
          </Link>
        </>
      )}
      {status === "timeout" && (
        <>
          <h1>Payment received</h1>
          <p>Credits may take a moment to appear. Refresh the page in 30 seconds.</p>
        </>
      )}
      {status === "error" && (
        <>
          <h1>Unable to verify payment status.</h1>
          <p>Please refresh or contact support.</p>
        </>
      )}
    </section>
  )
}

export default function Billing() {
  const [searchParams] = useSearchParams()
  const checkoutRef = searchParams.get("checkout_ref")

  const [loadState, setLoadState] = useState<LoadState>("loading")
  const [billingPackage, setBillingPackage] = useState<BillingPackage | null>(null)
  const [packs, setPacks] = useState<BillingCreditPack[]>([])
  const [balance, setBalance] = useState<number | null>(null)
  const [debtCredits, setDebtCredits] = useState(0)
  const [checkoutError, setCheckoutError] = useState<string | null>(null)
  const [isStartingCheckout, setIsStartingCheckout] = useState(false)
  const [pollingStatus, setPollingStatus] = useState<PollingStatus>(
    checkoutRef ? "processing" : "idle",
  )
  const [creditsAdded, setCreditsAdded] = useState<number | null>(null)
  const [completedExpiresAt, setCompletedExpiresAt] = useState<string | null>(null)
  // One-shot delight: tick the balance up in saffron when new credits land.
  const [balanceJustLanded, setBalanceJustLanded] = useState(false)

  const loadBillingData = useCallback(async (showLoading = true) => {
    if (showLoading) setLoadState("loading")
    try {
      // Data endpoints: GET /billing/package, GET /billing/history, GET /credits/balance.
      const [packageResponse, historyResponse, creditsResponse] = await Promise.all([
        fetchBillingPackage(),
        fetchBillingHistory(),
        getCredits(),
      ])
      setBillingPackage(packageResponse)
      setPacks(historyResponse)
      setBalance(creditsResponse.balance)
      // Payment-reversal debt is read here but rendered as a distinct note — it is
      // never added into the usable `balance` figure.
      setDebtCredits(creditsResponse.billing_debt_credits)
      setLoadState("ready")
    } catch {
      setLoadState("error")
    }
  }, [])

  useEffect(() => {
    void loadBillingData()
  }, [loadBillingData])

  useEffect(() => {
    if (!checkoutRef) {
      setPollingStatus("idle")
      setCreditsAdded(null)
      setCompletedExpiresAt(null)
      return
    }

    const ref = checkoutRef
    let elapsed = 0
    let inFlight = false
    let stopped = false
    let intervalId = 0
    let timeoutId = 0
    setPollingStatus("processing")
    setCreditsAdded(null)
    setCompletedExpiresAt(null)

    function stopPolling() {
      window.clearInterval(intervalId)
      window.clearTimeout(timeoutId)
    }

    async function pollStatus() {
      if (inFlight) return
      inFlight = true
      try {
        // Polling endpoint: GET /billing/status?checkout_ref=...
        // A null result is a 404 = "not granted yet" (pending); a thrown error is real.
        const result = await fetchBillingStatus(ref)
        if (stopped) return

        if (result?.status === "completed") {
          stopPolling()
          setPollingStatus("completed")
          setCreditsAdded(result.credits_added)
          setCompletedExpiresAt(result.expires_at)
          setBalanceJustLanded(true)
          void loadBillingData(false)
        } else if (elapsed >= 30) {
          stopPolling()
          setPollingStatus("timeout")
        }
      } catch {
        if (!stopped) {
          stopPolling()
          setPollingStatus("error")
        }
      } finally {
        inFlight = false
      }
    }

    intervalId = window.setInterval(() => {
      elapsed += 2
      void pollStatus()
    }, 2000)
    timeoutId = window.setTimeout(() => {
      if (stopped) return
      stopped = true
      stopPolling()
      setPollingStatus("timeout")
    }, 30_000)
    void pollStatus()

    return () => {
      stopped = true
      stopPolling()
    }
  }, [loadBillingData, checkoutRef])

  const balanceSummary = useMemo(() => activePackSummary(packs), [packs])

  async function handleBuyCredits() {
    if (isStartingCheckout) return
    setCheckoutError(null)
    setIsStartingCheckout(true)
    try {
      const response = await createCheckoutSession()
      window.location.href = response.checkout_url
    } catch (error) {
      setCheckoutError(
        getApiErrorMessage(error, "Could not open checkout. Please try again."),
      )
      setIsStartingCheckout(false)
    }
  }

  const packagePrice = billingPackage
    ? formatPrice(billingPackage.price_cents, billingPackage.currency)
    : null

  return (
    <div className="billing-page">
      <div className="ambient-field" aria-hidden="true">
        <div className="ambient-band band-saffron" />
        <div className="ambient-band band-lotus" />
        <div className="ambient-band band-slate" />
      </div>

      <BillingNav />

      <main className="billing-main">
        <PaymentStatusPanel
          status={pollingStatus}
          creditsAdded={creditsAdded}
          expiresAt={completedExpiresAt}
        />

        {loadState === "loading" && !billingPackage ? (
          <section className="billing-state-panel" aria-live="polite">
            <span className="billing-state-kicker">Billing</span>
            <h1>Preparing your credit options…</h1>
            <p>We are fetching your balance and the current package.</p>
          </section>
        ) : loadState === "error" && !billingPackage ? (
          <section className="billing-state-panel error" role="alert">
            <span className="billing-state-kicker">Billing</span>
            <h1>Could not load billing.</h1>
            <p>Please refresh and try again.</p>
            <button type="button" className="billing-secondary-btn" onClick={() => void loadBillingData()}>
              Try again
            </button>
          </section>
        ) : billingPackage ? (
          <>
            <section className="billing-balance-panel" aria-labelledby="billing-balance-title">
              <div>
                <p className="billing-eyebrow">Credit balance</p>
                <h1
                  id="billing-balance-title"
                  className={`billing-balance-value${balanceJustLanded ? " landed" : ""}`}
                  onAnimationEnd={() => setBalanceJustLanded(false)}
                >
                  {balance ?? "—"}
                </h1>
                <p className="billing-balance-label">credits remaining</p>
                {debtCredits > 0 && (
                  <p className="billing-debt-note" role="note">
                    {debtCredits} {debtCredits === 1 ? "credit" : "credits"} from a
                    reversed payment will be recovered from your next top-up.
                  </p>
                )}
              </div>
              <p className="billing-balance-summary">
                {balanceSummary ?? "Purchased credits will appear here after checkout."}
              </p>
            </section>

            <section className="billing-offer-grid" aria-label="Credit purchase options">
              <article className="billing-package-card">
                <div className="billing-package-copy">
                  <span className="billing-eyebrow">Credit pack</span>
                  <h2>{billingPackage.credits} credits</h2>
                  <p className="billing-package-price">{packagePrice}</p>
                  <p className="billing-package-validity">
                    {billingPackage.validity_days}-day validity
                  </p>
                </div>
                <button
                  type="button"
                  className="billing-buy-btn"
                  onClick={() => void handleBuyCredits()}
                  disabled={isStartingCheckout}
                >
                  {isStartingCheckout ? "Opening checkout…" : "Buy Credits →"}
                </button>
                {checkoutError && (
                  <p className="billing-checkout-error" role="alert">
                    {checkoutError}
                  </p>
                )}
              </article>
            </section>

            <section className="billing-history-section" aria-labelledby="billing-history-title">
              <div className="billing-section-header">
                <div>
                  <p className="billing-eyebrow">Purchase history</p>
                  <h2 id="billing-history-title">Credits ledger</h2>
                </div>
              </div>

              {packs.length === 0 ? (
                <div className="billing-empty-history">
                  <p>No purchases yet.</p>
                  <p>Credits are valid for {billingPackage.validity_days} days from purchase.</p>
                </div>
              ) : (
                <div className="billing-history-table-wrap">
                  <table className="billing-history-table">
                    <thead>
                      <tr>
                        <th scope="col">Date</th>
                        <th scope="col">Credits</th>
                        <th scope="col">Status</th>
                        <th scope="col">Expiry date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {packs.map((pack) => (
                        <tr key={pack.id}>
                          <td>{formatDate(pack.purchased_at)}</td>
                          <td>
                            {pack.credits_purchased} / {pack.credits_remaining}
                          </td>
                          <td>
                            <span className={`billing-status-chip ${pack.status}`}>
                              {statusLabels[pack.status]}
                            </span>
                          </td>
                          <td>{formatDate(pack.expires_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        ) : null}
        <AiDisclaimer variant="footer" className="billing-ai-disclaimer" />
      </main>
    </div>
  )
}

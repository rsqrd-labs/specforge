import { Link, useNavigate } from "react-router-dom"

import type { BillingCreditPack } from "../../types/billing"

interface CreditMeterProps {
  balance: number
  packs?: BillingCreditPack[]
  variant?: "default" | "inverse"
}

interface ExpiryWarning {
  credits: number
  label: string
  tone: "amber" | "urgent"
}

const DAY_MS = 24 * 60 * 60 * 1000

function calendarDaysUntil(date: Date): number {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  return Math.round((target.getTime() - today.getTime()) / DAY_MS)
}

function formatShortDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "soon"
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date)
}

function expiryLabel(expiresAt: string, daysRemaining: number): string {
  if (daysRemaining <= 0) return "today"
  if (daysRemaining === 1) return "tomorrow"
  if (daysRemaining <= 3) return `in ${daysRemaining} days`
  return formatShortDate(expiresAt)
}

function getExpiryWarning(packs: BillingCreditPack[]): ExpiryWarning | null {
  const soonest = packs
    .filter((pack) => pack.status === "active" && pack.credits_remaining > 0)
    .map((pack) => {
      const expiryDate = new Date(pack.expires_at)
      const expiresAt = expiryDate.getTime()
      const daysRemaining = calendarDaysUntil(expiryDate)
      return { pack, expiresAt, daysRemaining }
    })
    .filter(
      ({ expiresAt, daysRemaining }) =>
        !Number.isNaN(expiresAt) && daysRemaining >= 0 && daysRemaining <= 7,
    )
    .sort((a, b) => a.expiresAt - b.expiresAt)[0]

  if (!soonest) return null

  return {
    credits: soonest.pack.credits_remaining,
    label: expiryLabel(soonest.pack.expires_at, soonest.daysRemaining),
    tone: soonest.daysRemaining <= 3 ? "urgent" : "amber",
  }
}

export function CreditMeter({
  balance,
  packs = [],
  variant = "default",
}: CreditMeterProps) {
  const navigate = useNavigate()
  const expiryWarning = getExpiryWarning(packs)
  const isInverse = variant === "inverse"

  if (balance === 0) {
    return (
      <span className={`text-sm text-error${isInverse ? " credit-meter-zero-inverse" : ""}`}>
        You&apos;re at 0 credits.{" "}
        <Link to="/billing" className="underline font-medium">
          Buy more credits →
        </Link>
      </span>
    )
  }

  // The inverse variant is only ever composited over the dashboard's credit
  // card, which already leads with the balance as a giant number — restating
  // "N credits remaining" here duplicated that number a third time (after the
  // card's headline value and its low-balance qualifier). Only the
  // expiry-warning chip carries information the card doesn't already show.
  if (isInverse) {
    if (!expiryWarning) return null
    return (
      <span className="credit-meter">
        <button
          type="button"
          className={`credit-expiry-chip ${expiryWarning.tone} inverse`}
          onClick={() => navigate("/billing")}
        >
          {expiryWarning.credits} credits expire {expiryWarning.label} · Renew
        </button>
      </span>
    )
  }

  return (
    <span className="credit-meter">
      <span className="text-sm text-ink-text-muted">
        <span className="font-semibold text-ink-text">{balance}</span> credits remaining
      </span>
      {expiryWarning && (
        <button
          type="button"
          className={`credit-expiry-chip ${expiryWarning.tone}`}
          onClick={() => navigate("/billing")}
        >
          {expiryWarning.credits} credits expire {expiryWarning.label} · Renew
        </button>
      )}
    </span>
  )
}

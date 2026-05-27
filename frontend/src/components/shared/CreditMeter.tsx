import { Link, useNavigate } from "react-router-dom"

import type { StripeCreditPack } from "../../types/billing"

interface CreditMeterProps {
  balance: number
  packs?: StripeCreditPack[]
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

function getExpiryWarning(packs: StripeCreditPack[]): ExpiryWarning | null {
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

  return (
    <span className="credit-meter">
      <span
        className={
          isInverse ? "credit-meter-balance inverse" : "text-sm text-on-surface-variant"
        }
      >
        <span
          className={
            isInverse
              ? "credit-meter-balance-value inverse"
              : "font-semibold text-on-surface"
          }
        >
          {balance}
        </span>{" "}
        credits remaining
      </span>
      {expiryWarning && (
        <button
          type="button"
          className={`credit-expiry-chip ${expiryWarning.tone}${isInverse ? " inverse" : ""}`}
          onClick={() => navigate("/billing")}
        >
          {expiryWarning.credits} credits expire {expiryWarning.label} · Renew
        </button>
      )}
    </span>
  )
}

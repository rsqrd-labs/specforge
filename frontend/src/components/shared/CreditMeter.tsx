interface CreditMeterProps {
  balance: number
}

export function CreditMeter({ balance }: CreditMeterProps) {
  if (balance === 0) {
    return (
      <span className="text-sm text-error">
        You&apos;ve used all 50 free credits.{" "}
        <a href="#waitlist" className="underline font-medium">
          Join waitlist for more.
        </a>
      </span>
    )
  }

  return (
    <span className="text-sm text-on-surface-variant">
      <span className="font-semibold text-on-surface">{balance}</span> credits
      remaining
    </span>
  )
}

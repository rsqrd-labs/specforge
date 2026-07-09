import { CreditMeter } from "../shared/CreditMeter"

interface CreditBannerProps {
  balance: number
}

export function CreditBanner({ balance }: CreditBannerProps) {
  const isLow = balance <= 5

  return (
    <div
      className={`flex items-center rounded-lg border px-4 py-3 text-sm ${
        isLow
          ? "border-status-error/30 bg-status-error-soft text-status-error-soft-text"
          : "border-brand-primary-soft/40 bg-brand-primary-soft/10 text-brand-primary-soft-text"
      }`}
    >
      <CreditMeter balance={balance} />
    </div>
  )
}

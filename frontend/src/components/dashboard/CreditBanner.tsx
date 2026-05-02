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
          ? "border-error/30 bg-error-container text-on-error-container"
          : "border-primary-container/40 bg-primary-container/10 text-on-primary-container"
      }`}
    >
      <CreditMeter balance={balance} />
    </div>
  )
}

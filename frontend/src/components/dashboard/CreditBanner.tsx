import { CreditMeter } from "../shared/CreditMeter"

interface CreditBannerProps {
  balance: number
}

export function CreditBanner({ balance }: CreditBannerProps) {
  const isLow = balance <= 5

  return (
    <div
      className={`flex items-center justify-between px-4 py-2 rounded-lg text-sm ${
        isLow
          ? "bg-error-container text-on-error-container"
          : "bg-surface-container text-on-surface"
      }`}
    >
      <CreditMeter balance={balance} />
    </div>
  )
}

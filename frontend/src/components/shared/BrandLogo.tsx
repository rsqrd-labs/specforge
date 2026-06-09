export type BrandLogoSize = "default" | "small" | "compact"
export type BrandLockupVariant = "default" | "small" | "compact"

interface BrandLogoProps {
  size?: BrandLogoSize
  decorative?: boolean
  className?: string
}

interface BrandLockupProps {
  variant?: BrandLockupVariant
  className?: string
}

function classNames(...values: Array<string | false | undefined>): string {
  return values.filter(Boolean).join(" ")
}

export function BrandLogo({
  size = "default",
  decorative = false,
  className,
}: BrandLogoProps) {
  return (
    <span
      className={classNames("brand-logo", `brand-logo--${size}`, className)}
      aria-hidden={decorative ? true : undefined}
    >
      <img
        className="brand-logo-image"
        src="/brand/squirrel-mark.png"
        alt={decorative ? "" : "SpecForge squirrel logo"}
      />
    </span>
  )
}

export function BrandLockup({
  variant = "default",
  className,
}: BrandLockupProps) {
  return (
    <span
      className={classNames("brand-lockup", `brand-lockup--${variant}`, className)}
      role="img"
      aria-label="SpecForge"
    >
      <BrandLogo
        size={variant === "default" ? "default" : "small"}
        decorative
      />
      <span className="brand-wordmark" aria-hidden="true">
        SpecForge
      </span>
    </span>
  )
}

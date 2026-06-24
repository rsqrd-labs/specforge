import { SquirrelMark } from "./SquirrelMark"

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
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : "SpecForge squirrel logo"}
      aria-hidden={decorative ? true : undefined}
    >
      <SquirrelMark className="brand-logo-image" />
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

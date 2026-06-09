export const AI_DISCLAIMER_COPY =
  "Powered by AI. Outputs may contain mistakes; review before use."

export type AiDisclaimerVariant = "footer" | "sidebar" | "inline"

interface AiDisclaimerProps {
  variant?: AiDisclaimerVariant
  className?: string
}

export function AiDisclaimer({
  variant = "inline",
  className,
}: AiDisclaimerProps) {
  const classes = [
    "ai-disclaimer",
    `ai-disclaimer--${variant}`,
    className,
  ]
    .filter(Boolean)
    .join(" ")

  return (
    <p className={classes} role="note">
      {AI_DISCLAIMER_COPY}
    </p>
  )
}

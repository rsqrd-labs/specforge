interface StreamingOverlayProps {
  isVisible: boolean
}

export function StreamingOverlay({ isVisible }: StreamingOverlayProps) {
  if (!isVisible) {
    return null
  }

  return (
    <div className="pointer-events-none absolute inset-0 z-10 bg-surface/55">
      <div className="absolute bottom-4 right-4 flex items-center gap-2 rounded-md border border-outline-variant bg-surface/90 px-3 py-2 text-sm font-medium text-on-surface shadow-sm">
        <span className="h-4 w-0.5 animate-pulse bg-primary" />
        <span>Generating...</span>
      </div>
    </div>
  )
}

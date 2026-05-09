interface StreamingOverlayProps {
  isVisible: boolean
}

export function StreamingOverlay({ isVisible }: StreamingOverlayProps) {
  if (!isVisible) return null

  return (
    <div className="streaming-overlay">
      <div className="streaming-badge">
        <span className="streaming-cursor" />
        Generating…
      </div>
    </div>
  )
}

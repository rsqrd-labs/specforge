export interface Provider {
  id: "anthropic" | "openai" | "google"
  name: string
  configured: boolean
  selectable: boolean
  health: "not_configured" | "healthy" | "degraded" | "unhealthy"
  message: string
}

export const PROVIDERS: Provider[] = [
  {
    id: "anthropic",
    name: "Anthropic",
    configured: false,
    selectable: false,
    health: "not_configured",
    message: "Checking provider availability.",
  },
  {
    id: "openai",
    name: "OpenAI",
    configured: false,
    selectable: false,
    health: "not_configured",
    message: "Checking provider availability.",
  },
  {
    id: "google",
    name: "Google",
    configured: false,
    selectable: false,
    health: "not_configured",
    message: "Checking provider availability.",
  },
]

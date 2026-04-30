export interface ProviderModel {
  id: string
  name: string
}

export interface Provider {
  id: "anthropic" | "openai" | "google"
  name: string
  models: ProviderModel[]
}

export const PROVIDERS: Provider[] = [
  {
    id: "anthropic",
    name: "Anthropic",
    models: [
      { id: "claude-opus-4-7", name: "Claude Opus 4.7" },
      { id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6" },
      { id: "claude-haiku-4-5-20251001", name: "Claude Haiku 4.5" },
    ],
  },
  {
    id: "openai",
    name: "OpenAI",
    models: [
      { id: "gpt-4o", name: "GPT-4o" },
      { id: "gpt-4o-mini", name: "GPT-4o mini" },
    ],
  },
  {
    id: "google",
    name: "Google",
    models: [
      { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash" },
      { id: "gemini-1.5-pro", name: "Gemini 1.5 Pro" },
    ],
  },
]

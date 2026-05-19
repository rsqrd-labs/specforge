export interface StarterWorkspace {
  name: string
  description: string
  statement: string
}

export const STARTER_WORKSPACES: StarterWorkspace[] = [
  {
    name: "AI onboarding coach",
    description: "Personalized onboarding for new users",
    statement:
      "Build an AI onboarding coach for a B2B SaaS product. It should understand a new user's role, guide them through the first important setup steps, answer product questions, and surface success milestones for customer success teams.",
  },
  {
    name: "Customer feedback hub",
    description: "Turn user feedback into roadmap signals",
    statement:
      "Create a customer feedback hub that collects feedback from support tickets, calls, and surveys. Product managers should be able to cluster themes, identify priority requests, track customer impact, and turn validated insights into roadmap-ready work.",
  },
  {
    name: "Internal support copilot",
    description: "Help teams resolve operational questions",
    statement:
      "Design an internal support copilot for company operations. Employees should ask policy, tooling, and process questions, receive source-backed answers, and escalate unclear requests while administrators maintain approved knowledge sources.",
  },
]

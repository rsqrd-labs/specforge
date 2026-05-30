import type {
  SourceRef,
  StoryboardDiagramLayer,
  StoryboardLayerKind,
  StoryboardPayload,
  StoryboardPublicResponse,
  StoryboardSectionTitle,
  StoryboardSharePermissions,
} from "../../types/storyboard"

export const STORYBOARD_TEST_ACTS: StoryboardSectionTitle[] = [
  "Opening Thesis",
  "Product Vision",
  "Product Walkthrough",
  "Technical Architecture",
  "Trust, Security, Reliability",
  "Launch Close",
]

export const DEFAULT_TEST_PERMISSIONS: StoryboardSharePermissions = {
  allow_pdf_download: true,
  allow_notes_download: false,
  allow_appendix_download: false,
  allow_source_layer: false,
}

export function slideId(title: StoryboardSectionTitle): string {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "-")
}

function source(source: SourceRef["source"], excerpt = `${source} excerpt`): SourceRef {
  return {
    source,
    source_id: `${source}:source`,
    excerpt,
  }
}

function layer(kind: StoryboardLayerKind): StoryboardDiagramLayer {
  return {
    id: `${kind}-layer`,
    kind,
    label: `${kind} label`,
    summary: `${kind} summary`,
    source_refs: [source("PLAN", `${kind} architecture excerpt`)],
  }
}

export function makeStoryboardPayload(
  overrides: Partial<StoryboardPayload> = {},
): StoryboardPayload {
  const payload: StoryboardPayload = {
    title: "SpecForge Launch",
    theme: {
      palette: ["#8f4e00", "#a1385f", "#565e74"],
      typography: "Confident product sans",
      motif: "Copper circuit cards",
      transition_style: "Measured reveal",
      diagram_style: "Layered architecture cards",
    },
    sections: STORYBOARD_TEST_ACTS.map((title) => {
      const id = slideId(title)
      return {
        id,
        title,
        slides: [
          {
            id: `${id}-slide`,
            type: title === "Technical Architecture" ? "architecture" : "hero",
            headline: `${title} headline`,
            visible_text: `${title} visible text`,
            visual: { kind: `${id}-visual` },
            speaker_notes_ref: `${id}-slide`,
            sources: ["SPEC", "PLAN"],
          },
        ],
      }
    }),
    diagrams: [
      {
        id: "architecture-reveal",
        type: "architecture_reveal",
        layers: [
          layer("client"),
          layer("frontend"),
          layer("api"),
          layer("data"),
          layer("llm"),
          layer("integrations"),
          layer("trust"),
          layer("recovery"),
        ],
      },
    ],
    source_map: {
      "opening-thesis-slide.claim": [
        source("SPEC", "A".repeat(1500)),
        source("PLAN", "Plan excerpt"),
        source("HARNESS", "Harness excerpt"),
        source("TASKS", "Tasks excerpt"),
      ],
      "product-vision-slide.claim": [source("SPEC", "Vision excerpt")],
    },
    notes: Object.fromEntries(
      STORYBOARD_TEST_ACTS.map((title) => {
        const id = `${slideId(title)}-slide`
        return [
          id,
          {
            slide_id: id,
            talk_track: `${title} talk track`,
            transition: `${title} transition`,
            timing_seconds: 45,
            pause_cue: `${title} pause cue`,
            demo_cue: `${title} walkthrough cue`,
            backup_points: [`${title} backup point`],
          },
        ]
      }),
    ),
    demo_script_md: "Walkthrough script",
    technical_appendix_md: "Technical appendix",
  }

  return { ...payload, ...overrides }
}

export function makePublicStoryboard(
  overrides: Partial<StoryboardPublicResponse> = {},
): StoryboardPublicResponse {
  return {
    title: "SpecForge Launch",
    presentation: makeStoryboardPayload(),
    permissions: DEFAULT_TEST_PERMISSIONS,
    downloads: ["pdf"],
    shared_at: "2026-05-30T00:00:00Z",
    ...overrides,
  }
}

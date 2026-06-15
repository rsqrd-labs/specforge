import { create } from "zustand"

import {
  fetchGenerationEstimates,
  type GenerationEstimate,
} from "../services/api"

/**
 * Issue #21 Phase 2b — live, data-backed generation-ETA bands.
 *
 * The bands change slowly (a worker cron recomputes them every ~10 min and
 * caches them server-side), so the SPA fetches them at most once per session
 * and reuses the result for every generation. The fetch is best-effort and
 * non-blocking: an empty/failed load leaves `estimates` empty and every
 * consumer falls back to the constant heuristic table (Phase 2a). The loader is
 * never the thing that breaks the loading screen.
 */
interface GenerationEstimatesState {
  estimates: GenerationEstimate[]
  status: "idle" | "loading" | "loaded" | "error"
  /** Epoch ms of the last successful (or attempted) load; gates re-fetch. */
  fetchedAt: number | null
  /** Fetch once per session (idempotent). Safe to call on every overlay mount. */
  ensureLoaded: () => Promise<void>
}

// Re-fetch ceiling: the server cache lives ~15 min, so an hour-stale client copy
// is the worst case worth refreshing within a long-lived session.
const REFRESH_AFTER_MS = 60 * 60 * 1000

export const useGenerationEstimatesStore = create<GenerationEstimatesState>()(
  (set, get) => ({
    estimates: [],
    status: "idle",
    fetchedAt: null,

    ensureLoaded: async () => {
      const { status, fetchedAt } = get()
      if (status === "loading") return
      const fresh =
        fetchedAt !== null && Date.now() - fetchedAt < REFRESH_AFTER_MS
      if (status === "loaded" && fresh) return

      set({ status: "loading" })
      const estimates = await fetchGenerationEstimates()
      // fetchGenerationEstimates never throws; an empty list is a clean "no live
      // data" signal. Keep status "loaded" either way so consumers stop waiting
      // and the heuristic fallback takes over deterministically.
      set({ estimates, status: "loaded", fetchedAt: Date.now() })
    },
  }),
)

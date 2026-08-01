import { create } from "zustand"
import { getCurrentUser, isTransportError } from "../services/api"
import type { User } from "../types/user"

/**
 * Whether the last session probe could talk to the API at all.
 *
 * `"unreachable"` means the request never produced a response — a blocked
 * corporate proxy, a rejected CORS preflight, a timeout, an offline browser.
 * It is deliberately NOT the same as "signed out": treating the two alike is
 * what made a network block present as a silent logout, with the user bounced
 * to the landing page and no error anywhere.
 */
export type Reachability = "ok" | "unreachable"

interface UserState {
  user: User | null
  isLoading: boolean
  reachability: Reachability
  setUser: (user: User | null) => void
  clearUser: () => void
  fetchMe: () => Promise<void>
}

export const useUserStore = create<UserState>((set) => ({
  user: null,
  isLoading: false,
  reachability: "ok",

  setUser: (user) => set({ user }),

  clearUser: () => set({ user: null }),

  fetchMe: async () => {
    set({ isLoading: true })
    try {
      const user = await getCurrentUser()
      set({ user, isLoading: false, reachability: "ok" })
    } catch (error) {
      if (isTransportError(error)) {
        // We could not ask the question, so we have learned nothing about the
        // session — leave `user` exactly as it was. A signed-in user stays
        // signed in and sees an "unreachable" surface with a retry; a
        // signed-out one is still signed out.
        set({ isLoading: false, reachability: "unreachable" })
        return
      }
      set({ user: null, isLoading: false, reachability: "ok" })
    }
  },
}))

import { create } from "zustand"
import { getCurrentUser } from "../services/api"
import type { User } from "../types/user"

interface UserState {
  user: User | null
  isLoading: boolean
  setUser: (user: User | null) => void
  clearUser: () => void
  fetchMe: () => Promise<void>
}

export const useUserStore = create<UserState>((set) => ({
  user: null,
  isLoading: false,

  setUser: (user) => set({ user }),

  clearUser: () => set({ user: null }),

  fetchMe: async () => {
    set({ isLoading: true })
    try {
      const user = await getCurrentUser()
      set({ user, isLoading: false })
    } catch {
      set({ user: null, isLoading: false })
    }
  },
}))

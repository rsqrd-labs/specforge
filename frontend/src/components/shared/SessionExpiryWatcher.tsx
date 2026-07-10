import { useEffect } from "react"
import { onSessionExpired } from "../../services/api"
import { useUserStore } from "../../store/userStore"
import { useActionAlert } from "./ActionAlert"

/**
 * Headless subscriber for api.ts's "session confirmed dead" signal. Mount
 * once, outside <Routes>, so it survives every navigation.
 *
 * Without this, an idle tab whose access token expires mid-session has no way
 * to learn that its refresh token is *definitively* gone: every independent
 * poller (credits, GitHub sync, increment timeline, billing status) would
 * keep silently retrying /auth/refresh forever, each failing the same way,
 * with the user never told why their data stopped updating. Clearing the user
 * here lets the existing ProtectedRoute reactively redirect to sign-in, which
 * unmounts Dashboard/Workspace/Billing/Storyboard and, with them, every
 * setInterval poll those pages own — no per-hook changes needed.
 */
export function SessionExpiryWatcher() {
  const clearUser = useUserStore((state) => state.clearUser)
  const { showAlert } = useActionAlert()

  useEffect(() => {
    return onSessionExpired(() => {
      // Only announce it if there was actually a session to lose — a guest
      // landing on a protected route cold also triggers a rejected refresh,
      // and that is not a "you were signed out" event worth alarming anyone
      // over (a false alarm the Boy-Who-Cried-Wolf moral warns against).
      const hadUser = useUserStore.getState().user !== null
      clearUser()
      if (hadUser) {
        showAlert({
          severity: "warning",
          title: "Session expired",
          message:
            "You were signed out because your session expired. Please sign in again to continue.",
          source: "Session",
          dismissLabel: "OK",
        })
      }
    })
  }, [clearUser, showAlert])

  return null
}

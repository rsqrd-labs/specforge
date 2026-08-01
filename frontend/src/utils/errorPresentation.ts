import type {
  ActionAlertAction,
  ActionAlertContent,
  ActionAlertSeverity,
} from "../components/shared/ActionAlert"
import { getApiErrorMessage } from "../services/api"

interface StreamLikeError {
  code: string
  message: string
}

interface AlertOptions {
  primaryAction?: ActionAlertAction
  secondaryAction?: ActionAlertAction
  dismissLabel?: string
}

export function actionAlertFromMessage({
  title,
  message,
  recovery,
  severity = "error",
  source,
  primaryAction,
  secondaryAction,
  dismissLabel,
}: {
  title: string
  message: string
  recovery?: string
  severity?: ActionAlertSeverity
  source?: string
} & AlertOptions): ActionAlertContent {
  return {
    severity,
    title,
    message,
    recovery,
    source,
    primaryAction,
    secondaryAction,
    dismissLabel,
  }
}

export function actionAlertFromApiError(
  error: unknown,
  {
    title,
    fallback,
    recovery = "Your work is safe. Try the action again, or refresh if the problem continues.",
    source,
    primaryAction,
    secondaryAction,
    dismissLabel,
  }: {
    title: string
    fallback: string
    recovery?: string
    source?: string
  } & AlertOptions,
): ActionAlertContent {
  return actionAlertFromMessage({
    title,
    message: getApiErrorMessage(error, fallback),
    recovery,
    source,
    primaryAction,
    secondaryAction,
    dismissLabel,
  })
}

export function actionAlertFromStreamError(
  error: StreamLikeError,
  options: AlertOptions = {},
): ActionAlertContent {
  switch (error.code) {
    case "generation_timeout":
      return actionAlertFromMessage({
        title: "Generation timed out",
        message:
          "Generation did not finish this stage in time. Your workspace is safe. Try again; long stages may need another run.",
        recovery: "No credits are charged for backend-failed paid generation runs.",
        source: "Generation",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    case "generation_unavailable":
      return actionAlertFromMessage({
        title: "Generation is temporarily unavailable",
        message:
          "The generation service could not complete this stage. Try again in a moment.",
        recovery: "Your current draft and edits are still saved.",
        source: "Generation",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    case "rate_limit_exceeded":
      return actionAlertFromMessage({
        title: "Generation is busy",
        message:
          "Thought2Build is receiving too many generation requests right now. Wait a moment, then try again.",
        recovery: "You do not need to change your input.",
        source: "Generation",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    case "insufficient_credits":
      return actionAlertFromMessage({
        title: "Not enough credits",
        message: "Add credits before generating this stage.",
        recovery: "Your workspace is unchanged.",
        source: "Billing",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    case "dependency_not_finalised":
      return actionAlertFromMessage({
        title: "Previous stage needs finalising",
        message: "Finish the previous stage before generating this one.",
        recovery: "Finalise the previous stage, then return here to continue.",
        source: "Workspace",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    case "stage_not_generatable":
      return actionAlertFromMessage({
        title: "Stage is already finalised",
        message: "Unlock the stage before regenerating it.",
        recovery: "Use rollback or edit the draft, then run generation again.",
        source: "Workspace",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    case "no_new_coverage":
      return actionAlertFromMessage({
        title: "No new coverage to add",
        message:
          "The patch didn't find any new test files to add — your harness is " +
          "unchanged and you were not charged.",
        recovery:
          "If a requirement still looks uncovered, regenerate the HARNESS stage " +
          "to rebuild its tests from scratch.",
        source: "Coverage patch",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    case "security_check_failed":
      return actionAlertFromMessage({
        title: "Generation stopped by safety checks",
        message: "The generated output did not pass Thought2Build safety checks.",
        recovery: "Regenerate the stage or adjust the input before trying again.",
        source: "Generation",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    case "quality_gate_failed":
      return actionAlertFromMessage({
        title: "Quality gate held this generation back",
        message: error.message,
        recovery: "Review the findings in the workspace, then regenerate or override if allowed.",
        source: "Quality gate",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    case "session_expired":
      // Defense in depth: the app-level SessionExpiryWatcher (subscribed to
      // api.ts's onSessionExpired) is the primary path — it clears the user
      // and redirects to sign-in. This case only fires if a StreamError with
      // this code reaches here through some other path, so it must still say
      // something true rather than fall through to the generic message.
      return actionAlertFromMessage({
        title: "Session expired",
        message: "Your session has expired. Please sign in again to continue.",
        source: "Session",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
    default:
      return actionAlertFromMessage({
        title: "Action could not finish",
        message: error.message || "Something went wrong while generating.",
        recovery: "Your workspace is safe. Try again, or refresh if the problem continues.",
        source: "Generation",
        primaryAction: options.primaryAction,
        secondaryAction: options.secondaryAction,
        dismissLabel: options.dismissLabel,
      })
  }
}

export function billingAlert(
  kind: "load" | "checkout" | "payment-timeout" | "payment-error",
  options: AlertOptions = {},
): ActionAlertContent {
  if (kind === "checkout") {
    return actionAlertFromMessage({
      title: "Checkout could not open",
      message: "Your credits were not charged. Try again from Billing.",
      recovery: "If this keeps happening, refresh Billing before starting checkout again.",
      source: "Billing",
      primaryAction: options.primaryAction,
      secondaryAction: options.secondaryAction,
      dismissLabel: options.dismissLabel,
    })
  }

  if (kind === "payment-timeout") {
    return actionAlertFromMessage({
      title: "Payment received, credits still syncing",
      message: "Refresh in 30 seconds; your checkout is being reconciled.",
      recovery: "Do not start another checkout for this same purchase yet.",
      severity: "warning",
      source: "Billing",
      primaryAction: options.primaryAction,
      secondaryAction: options.secondaryAction,
      dismissLabel: options.dismissLabel,
    })
  }

  if (kind === "payment-error") {
    return actionAlertFromMessage({
      title: "Payment status could not be verified",
      message: "Thought2Build could not confirm the checkout status right now.",
      recovery: "Refresh Billing. If credits do not appear, contact support with your checkout reference.",
      source: "Billing",
      primaryAction: options.primaryAction,
      secondaryAction: options.secondaryAction,
      dismissLabel: options.dismissLabel,
    })
  }

  return actionAlertFromMessage({
    title: "Billing could not load",
    message: "Thought2Build could not fetch your balance, package, or purchase history.",
    recovery: "Try again. Your existing credits and purchases are not changed by this display error.",
    source: "Billing",
    primaryAction: options.primaryAction,
    secondaryAction: options.secondaryAction,
    dismissLabel: options.dismissLabel,
  })
}

export function githubConnectionAlert(
  kind: "load" | "install" | "not-configured" | "disconnect",
  options: AlertOptions = {},
): ActionAlertContent {
  if (kind === "not-configured") {
    return actionAlertFromMessage({
      title: "GitHub App is not configured",
      message:
        "This environment is missing the Thought2Build GitHub App configuration.",
      recovery: "Ask an admin to enable the Thought2Build GitHub App, then try again.",
      source: "GitHub",
      primaryAction: options.primaryAction,
      secondaryAction: options.secondaryAction,
      dismissLabel: options.dismissLabel,
    })
  }

  if (kind === "install") {
    return actionAlertFromMessage({
      title: "GitHub could not open",
      message: "Thought2Build could not open the GitHub App installation flow.",
      recovery: "Try again. Your workspaces are safe.",
      source: "GitHub",
      primaryAction: options.primaryAction,
      secondaryAction: options.secondaryAction,
      dismissLabel: options.dismissLabel,
    })
  }

  if (kind === "disconnect") {
    return actionAlertFromMessage({
      title: "GitHub disconnect failed",
      message: "Thought2Build could not remove this GitHub installation.",
      recovery: "Try again, or manage the installation directly on GitHub.",
      source: "GitHub",
      primaryAction: options.primaryAction,
      secondaryAction: options.secondaryAction,
      dismissLabel: options.dismissLabel,
    })
  }

  return actionAlertFromMessage({
    title: "GitHub connection could not be loaded",
    message: "Your workspaces are safe. Try again or reinstall the GitHub App.",
    recovery: "Live sync may be paused until the connection loads.",
    source: "GitHub",
    primaryAction: options.primaryAction,
    secondaryAction: options.secondaryAction,
    dismissLabel: options.dismissLabel,
  })
}

export function authCallbackAlert(
  reason: "cancelled" | "missing-code" | "exchange-failed",
): ActionAlertContent {
  if (reason === "cancelled") {
    return actionAlertFromMessage({
      title: "Sign-in was cancelled",
      message: "Google did not grant access to finish signing you in.",
      recovery: "Try again when you are ready, or return home.",
      source: "Sign-in",
    })
  }

  if (reason === "missing-code") {
    return actionAlertFromMessage({
      title: "Google did not return a sign-in code",
      message: "Thought2Build could not complete sign-in because the callback was incomplete.",
      recovery: "Start sign-in again from the home page.",
      source: "Sign-in",
    })
  }

  return actionAlertFromMessage({
    title: "Google sign-in failed",
    message: "Thought2Build could not exchange the Google response for a session.",
    recovery: "Check the OAuth configuration if this keeps happening.",
    source: "Sign-in",
  })
}

/**
 * The API could not be reached at all — as opposed to answering with an error.
 * Names the exact host so someone behind a corporate proxy (the case this was
 * written for) can hand IT something actionable instead of guessing.
 */
export function apiUnreachableAlert(options: AlertOptions = {}): ActionAlertContent {
  return actionAlertFromMessage({
    title: "We can't reach Thought2Build",
    // Deliberately says nothing about session state: this alert renders both
    // for a signed-in user whose session is untouched and for a visitor who
    // never signed in. Claiming either would be the same unfounded assertion
    // the silent redirect used to make.
    message: `Your browser could not connect to ${apiHostLabel()}. The request never reached our servers, so nothing has changed on your account.`,
    recovery:
      "This is usually a network, VPN, or corporate firewall block. Retry, or ask IT to allow that address.",
    source: "Connection",
    ...options,
  })
}

/** Hostname of the API, for display only. Falls back to the page's own origin
 *  when the API is same-origin (a relative `VITE_API_URL`). */
function apiHostLabel(): string {
  const configured = import.meta.env.VITE_API_URL
  try {
    return new URL(configured ?? "", window.location.origin).host
  } catch {
    return window.location.host
  }
}

export function storyboardLoadAlert(
  message: string,
  options: AlertOptions = {},
): ActionAlertContent {
  return actionAlertFromMessage({
    title: "Storyboard could not be loaded",
    message: message || "Try again, or return to the workspace.",
    recovery: "If the Storyboard is still generating, return to the workspace and check its latest status.",
    source: "Storyboard",
    primaryAction: options.primaryAction,
    secondaryAction: options.secondaryAction,
    dismissLabel: options.dismissLabel,
  })
}

export function publicLinkUnavailableAlert(
  kind: "workspace" | "storyboard",
): ActionAlertContent {
  return actionAlertFromMessage({
    title:
      kind === "workspace"
        ? "This shared workspace link is no longer available"
        : "This Storyboard link is no longer available",
    message: "This link may have been disabled, rotated, or mistyped.",
    recovery:
      kind === "workspace"
        ? "Ask the owner for a fresh workspace share link."
        : "Ask the owner for a fresh Storyboard link.",
    severity: "info",
    source: "Public link",
  })
}

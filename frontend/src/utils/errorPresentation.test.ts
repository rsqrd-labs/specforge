import { describe, expect, it } from "vitest"
import {
  authCallbackAlert,
  billingAlert,
  githubConnectionAlert,
  publicLinkUnavailableAlert,
  storyboardLoadAlert,
  actionAlertFromStreamError,
} from "./errorPresentation"

describe("error presentation mappers", () => {
  it("maps provider timeouts to clear generation recovery copy", () => {
    const alert = actionAlertFromStreamError({
      code: "generation_timeout",
      message: "raw timeout",
    })

    expect(alert.title).toBe("Generation timed out")
    expect(alert.message).toMatch(/generation did not finish/i)
    expect(alert.message).toMatch(/workspace is safe/i)
    expect(alert.source).toBe("Generation")
  })

  it("maps session_expired to an honest, actionable message", () => {
    // Defense-in-depth path: the app-level SessionExpiryWatcher is the
    // primary handler for a dead session, but any StreamError with this code
    // that reaches this mapper (rather than being filtered upstream) must
    // still say something true, not fall through to the generic copy.
    const alert = actionAlertFromStreamError({
      code: "session_expired",
      message: "raw code, not shown to the user",
    })

    expect(alert.title).toBe("Session expired")
    expect(alert.message).toMatch(/sign in again/i)
    expect(alert.source).toBe("Session")
  })

  it("maps billing checkout and payment states to user-safe copy", () => {
    expect(billingAlert("checkout").message).toMatch(/not charged/i)
    expect(billingAlert("payment-timeout").title).toMatch(/credits still syncing/i)
    expect(billingAlert("payment-error").recovery).toMatch(/checkout reference/i)
  })

  it("maps GitHub connection failures without implying workspace damage", () => {
    const alert = githubConnectionAlert("load")

    expect(alert.title).toMatch(/could not be loaded/i)
    expect(alert.message).toMatch(/workspaces are safe/i)
  })

  it("maps auth callback failures to explicit next steps", () => {
    expect(authCallbackAlert("missing-code").title).toMatch(/sign-in code/i)
    expect(authCallbackAlert("exchange-failed").recovery).toMatch(/OAuth/i)
  })

  it("maps storyboard and public link failures", () => {
    expect(storyboardLoadAlert("Boom").title).toBe("Storyboard could not be loaded")
    expect(publicLinkUnavailableAlert("workspace").message).toMatch(/disabled/i)
    expect(publicLinkUnavailableAlert("storyboard").recovery).toMatch(/Storyboard link/i)
  })
})

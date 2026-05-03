/**
 * Harness contracts for T-091: Eliminate frontend eval polling — deliver via SSE event.
 * RED before T-091 is implemented (pollEval exists, no SSE eval event handling).
 * GREEN after pollEval is removed and sseService/useStream handle the eval event.
 */
import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { resolve, dirname } from "node:path"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")
const FRONTEND_SRC = resolve(REPO_ROOT, "frontend/src")

describe("T-091: Eval polling replaced by SSE eval event", () => {
  it("useStream.ts does not define a pollEval function", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "hooks/useStream.ts"),
      "utf-8",
    )
    expect(source).not.toContain("pollEval")
  })

  it("useStream.ts does not contain a pollEval function (polling mechanism removed)", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "hooks/useStream.ts"),
      "utf-8",
    )
    // The polling mechanism was a function called pollEval that awaited repeated getEval calls
    expect(source).not.toContain("pollEval")
    // And must not call the REST /stages/.../eval polling endpoint
    expect(source).not.toMatch(/\/stages\/.*\/eval|getEval\s*\(/)
  })

  it("sseService.ts defines an EvalEvent type or interface", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    // Must have some eval event type definition
    expect(source).toMatch(/eval.*EvalResult|EvalEvent|"eval"\s*:/i)
  })

  it("sseService.ts handles the eval key in the SSE payload dispatch", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    // Must branch on "eval" in data
    expect(source).toMatch(/"eval"\s+in\s+data|data\s*\.\s*eval/)
  })

  it("sseService.ts createSSEConnection accepts an onEval callback", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    expect(source).toContain("onEval")
  })

  it("useStream.ts populates evalResult from the SSE eval event via onEval callback", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "hooks/useStream.ts"),
      "utf-8",
    )
    // Must pass an onEval callback to createSSEConnection (the SSE-driven path)
    expect(source).toContain("onEval")
    // Must not use the old pollEval polling function
    expect(source).not.toContain("pollEval")
  })

  it("backend stage_manager.py emits an eval SSE event after the done event", () => {
    const stageManagerSource = readFileSync(
      resolve(REPO_ROOT, "backend/services/pipeline/stage_manager.py"),
      "utf-8",
    )
    // Should have an eval dict or _eval_to_dict helper, and yield it
    const hasEvalEmission =
      stageManagerSource.includes("_eval_to_dict") ||
      (stageManagerSource.includes('"eval"') && stageManagerSource.includes("yield"))
    expect(hasEvalEmission).toBe(
      true,
    )
  })

  it("backend stage_manager.py uses asyncio.wait_for with a 30s timeout for eval", () => {
    const source = readFileSync(
      resolve(REPO_ROOT, "backend/services/pipeline/stage_manager.py"),
      "utf-8",
    )
    // Should guard the eval await with a timeout to prevent blocking the stream
    const hasTimeout =
      source.includes("wait_for") &&
      (source.includes("30") || source.includes("timeout"))
    expect(hasTimeout).toBe(true)
  })
})

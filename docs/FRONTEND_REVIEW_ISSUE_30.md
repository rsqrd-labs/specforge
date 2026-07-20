# Issue #30 — End-to-End Frontend Review and Hardening

## Baseline and scope

- Audit SHA: `d94da8b71a0438b1c9ca247cfb10a835af694b41`
- Audit date: 2026-07-21 (Asia/Kolkata)
- Runtime evidence: Node 24.14.1 locally; CI Node 22; pnpm 11.13.0 policy
- Baseline lock hash: `0cff89916e48e063ddae3f1582c73d7c42c052d5ce9aab8b625dfa2099aa511c`
- Scope: 221 tracked frontend files plus 24 backend router/schema contract sources. See `FRONTEND_REVIEW_ISSUE_30_MANIFEST.md`.
- Supported matrix: current Chromium, Firefox, WebKit/Safari, iPhone 13, and Pixel 7; English only.

Historical “Stage 1” language in issue #30 was treated as context only. The review targets the complete current frontend.

## Release recommendation

**Approve with conditions.** No confirmed Critical or High frontend defect remains. Dependency, build, browser-accessibility, security-header, contract-drift, lint, full-harness, and bundle-regression controls are remediated in this work. Coverage is now measured and ratcheted in CI, but the requested 80% aggregate and 90% critical-boundary targets remain an open Medium test-engineering workstream; issue #30 must remain open until that work and the Docker-backed authenticated journey suite land.

## Findings

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| FE30-001 | Medium | Axios 1.17 carried three moderate advisories | Remediated: Axios 1.18.1; audit clean |
| FE30-002 | Medium | SPA deployment supplied no explicit CSP or browser hardening headers | Remediated in `frontend/vercel.json` |
| FE30-003 | Medium | No real-browser, mobile, or automated accessibility release gate | Remediated: five Playwright projects, axe serious/critical gate, zoom/overflow check |
| FE30-004 | Medium | Aggregate coverage is below the requested policy | Open: #48; 64.88% statements, 61.58% branches, 61.71% functions, 67.26% lines |
| FE30-005 | Medium | No Docker-backed authenticated critical-journey browser suite | Open: #49; existing component/API/SSE tests remain green |
| FE30-006 | Low | Production build emitted unresolved Tailwind at-rule warnings | Remediated with explicit PostCSS/Tailwind processing |
| FE30-007 | Low | CI lacked ESLint, complete harness, OpenAPI drift, and bundle budgets | Remediated with blocking gates |
| FE30-008 | Low | Unused Stripe browser SDK remained after payment-provider decommission | Removed |

## Evidence

| Gate | Baseline | Hardened result |
|---|---|---|
| TypeScript strict check | Pass | Pass |
| Unit/component tests | 567 pass | 567 pass |
| Complete frontend harness | 170 pass; CI selected only three files | 170 pass; full suite gated |
| Dependency audit | Three moderate Axios advisories | No known vulnerabilities |
| Production build | Pass with three Tailwind warnings | Warning-free; bundle budgets pass |
| ESLint | Not configured | Production source passes with zero warnings |
| Coverage | Not measured/gated | Measured and 60% baseline-ratcheted; FE30-004 tracks policy target |
| Browser/accessibility | None | 25/25 across five projects; no serious/critical axe violations |
| OpenAPI drift | Manual frontend models only | Generated schema types committed and regeneration diff-gated |
| Security headers | Rewrites only | CSP, referrer, permissions, nosniff, and frame protections |

Measured gzip budgets are CSS 55 KiB, initial application 36 KiB, React 58 KiB, Workspace 58 KiB, Markdown renderer 110 KiB, and CodeMirror 170 KiB. The hardened build currently passes all six.

## Boundary review conclusions

- **Auth/API/SSE:** in-memory access tokens, single-flight refresh, session-expiry cooldown, CSRF acquisition, error normalization, retry boundaries, stream abort, terminal events, and reconnect paths were traced. Existing focused tests cover refresh, CSRF, malformed SSE, retry, abort, teardown, generation terminal states, and quality gates. Generated OpenAPI types now expose backend drift.
- **Security/privacy:** Markdown runs through `rehype-sanitize` before highlighting; external links use opener protection; public routes remain outside auth; Sentry is opt-in. Deployment now supplies a restrictive policy compatible with the configured HTTPS API/Sentry/font connections and blob downloads.
- **Accessibility/responsive:** static JSX rules, axe browser scans, keyboard-oriented component tests, reduced-motion CSS, five viewport engines, and 200% zoom are covered. No serious/critical violation was reproduced on the public route set.
- **Performance:** heavy editor/secondary routes remain lazy-loaded. Measured chunks are budgeted instead of relying on intuition. No performance defect was published without bundle evidence.
- **Maintainability:** production-source linting and API generation are enforceable. The large Workspace/API/CSS modules remain refactoring candidates, but size alone is not treated as a runtime defect.

## Remaining remediation queue

1. Raise coverage monotonically to 80% aggregate and 90% for auth, API/SSE, stores, and critical hooks. Prioritize `api.ts`, `workspaceStore.ts`, `WorkspaceGitHub.tsx`, `Workspace.tsx`, Dashboard, and untested workspace/export components; require negative and race tests rather than shallow render coverage.
2. Add a Docker-backed authenticated Playwright lane using deterministic provider fakes for login bootstrap, workspace CRUD, generation lifecycle/cancel/reconnect, finalisation, public sharing, and disabled billing/GitHub behavior.
3. After both Medium workstreams pass on all supported browsers, update this report with final evidence and change the recommendation to **approve**.

## Acceptance checklist

- [x] Every baseline frontend and browser-consumed backend contract file appears in the manifest.
- [x] Dependency advisories and CSS build warnings are resolved.
- [x] ESLint, complete harness, OpenAPI drift, bundle, browser, mobile, and accessibility gates are implemented.
- [x] Production security headers are defined.
- [x] Existing unit/component and contract suites remain green.
- [ ] Aggregate coverage reaches 80% and critical boundaries reach 90%.
- [ ] Docker-backed authenticated critical journeys pass.
- [ ] No open Critical/High/Medium finding remains and issue #30 receives an unconditional release approval.

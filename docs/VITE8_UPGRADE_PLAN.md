# Vite 6 → 8 Upgrade Plan (eliminate esbuild CVE GHSA-gv7w-rqvm-qjhr)

## Goal

Permanently remove the high-severity **esbuild** advisory (`GHSA-gv7w-rqvm-qjhr`,
"Missing binary integrity verification in Deno module") from the frontend
dependency tree — not suppress it. The vulnerability is patched only in
esbuild `>= 0.28.1`, but forcing that version via a pnpm override **breaks the
Vite 6 build** (`Transforming destructuring to the configured target
environment … is not supported yet`). The clean fix is to move off the esbuild
toolchain entirely.

## Why this closes it "once and for all"

`pnpm why esbuild` proves esbuild enters the tree through **exactly one root**:

```
@vitejs/plugin-react 4.7.0 └─┬ vite 6.4.2 peer └── esbuild 0.25.12
vite 6.4.2                        └── esbuild 0.25.12
vitest 4.1.8 ├─┬ @vitest/mocker → vite 6.4.2 peer └── esbuild 0.25.12
             └─┬ vite 6.4.2 peer                  └── esbuild 0.25.12
```

Every path is `… → vite 6 → esbuild`. **Vite 8 dropped the esbuild dependency**
(it bundles with **rolldown** and transforms/minifies with **oxc /
lightningcss**). `npm view vite@8.0.16 dependencies` → `postcss, rolldown,
picomatch, tinyglobby, lightningcss` — no esbuild. Once Vite is on 8 and the
React plugin is on a Vite-8-compatible major, `pnpm why esbuild` returns
nothing and `pnpm audit --audit-level moderate` is genuinely clean with **no
ignore entry**.

## Compatibility matrix (verified against the npm registry)

| Package | Current | Target | Constraint |
|---|---|---|---|
| `vite` | `^6.4.2` | `^8.0.16` | engines `node ^20.19.0 \|\| >=22.12.0` |
| `@vitejs/plugin-react` | `^4.3` (4.7.0) | `^6.0.2` | peer `vite ^8.0.0`; extra peers (`@rolldown/plugin-babel`, `babel-plugin-react-compiler`) are **optional** — no new deps; only dep is `@rolldown/pluginutils` |
| `vitest` | `^4.1.8` | **unchanged** | already declares peer `vite ^6 \|\| ^7 \|\| ^8` |
| `@vitest/*` (if added later) | n/a | match vitest `4.1.8` | — |

**Node:** local `v24.14.1` ✓. CI frontend job uses `actions/setup-node` with
`node-version: "22"` → resolves to latest 22.x (≥ 22.12) ✓. No CI Node bump
required; consider pinning to `22.12` for determinism (optional).

**TypeScript config:** `tsconfig` already `module: ESNext`,
`moduleResolution: Bundler`, `target: ES2022`, and `package.json` has
`"type": "module"` — all Vite-8-compatible. No tsconfig change expected.

## Risk register

1. **Bundler swap rollup → rolldown.** `vite.config.ts` sets
   `build.rollupOptions.output.manualChunks` (object form). rolldown implements
   the rollup-compatible `manualChunks` object API, but this is the single
   highest-risk surface — must be validated by a real `vite build` and a chunk
   sanity check (codemirror / react / vendor chunks still emitted).
2. **Default build target moves to `baseline-widely-available`** (≈ Chrome 107
   / Edge 107 / Firefox 104 / Safari 16) vs. Vite 6's older default. Acceptable
   for this SaaS app; if a specific floor is required, set `build.target`
   explicitly. Decide and document, don't inherit silently.
3. **CSS pipeline.** Vite 6 minified CSS with esbuild; Vite 8 uses
   lightningcss/oxc. Tailwind v3 runs through PostCSS (`postcss` is still a Vite
   dep) so the authoring pipeline is unchanged, but minified CSS output must be
   eyeballed in `dist/`.
4. **Two Vite configs.** `vite.config.ts` (app + `pnpm test`) **and**
   `vitest.harness.config.ts` (CI harness contracts) both import
   `@vitejs/plugin-react` — both must build/run after the bump.
5. **Transitive esbuild re-entry.** After the bump, re-run `pnpm why esbuild`;
   if any other dep reintroduces it, that path must be addressed before
   declaring done (acceptance criterion below).

## Execution phases

### Phase 0 — Branch + baseline (no changes)
- Create branch `chore/vite8-upgrade` off `main`.
- Record green baseline on Vite 6: `pnpm install --frozen-lockfile`,
  `pnpm tsc`, `pnpm test` (currently 266 pass), `pnpm build`,
  `pnpm vitest run --config vitest.harness.config.ts <each harness contract>`.
  This is the rollback reference.

### Phase 1 — Bump manifests
- `frontend/package.json`: `vite` `^6.4.2 → ^8.0.16`,
  `@vitejs/plugin-react` `^4.3 → ^6.0.2`. Leave `vitest ^4.1.8` as-is.
- `pnpm install` (regenerates `pnpm-lock.yaml`).
- **Gate A:** `pnpm why esbuild` → must print nothing (package gone).

### Phase 2 — Config reconciliation
- Run `pnpm build`; if rolldown rejects `manualChunks`, migrate the object form
  to the rolldown-supported shape (object form is expected to work; function
  form is the fallback). Keep the three chunks (codemirror / react / vendor).
- Decide `build.target`: accept the new `baseline-widely-available` default
  (document it) or pin explicitly.
- Confirm `server.proxy` (`/api → :8000`) and `server.watch.usePolling` still
  type-check and run under `pnpm dev`.
- Apply the same plugin bump effects to `vitest.harness.config.ts`.

### Phase 3 — Validate (all must pass)
- `pnpm tsc` (no type errors).
- `pnpm test` — full vitest suite green (baseline 266 tests).
- `pnpm build` — succeeds; inspect `dist/` for the expected chunks and
  non-empty minified CSS.
- `pnpm vitest run --config vitest.harness.config.ts` for the three CI harness
  contracts (phase13 / phase14 / phase24).
- `pnpm dev` smoke: app boots, `/api` proxy works.

### Phase 4 — Security verification (the actual goal)
- `pnpm audit --audit-level moderate` → exit 0 with **no** `auditConfig`
  ignore entry in `package.json`.
- `pnpm why esbuild` → empty.
- Dismiss/confirm-fixed Dependabot alert #5 after the lockfile lands on `main`
  (Dependabot auto-resolves once the vulnerable version leaves the lockfile).

### Phase 5 — CI + ship
- Push branch; confirm the **frontend** CI job (`pnpm install --frozen-lockfile`
  → `pnpm audit` → `pnpm tsc` → `pnpm test` → 3 harness contracts →
  `pnpm build`) is fully green.
- Open PR, merge to `main`.

## Acceptance criteria

- [x] `pnpm why esbuild` prints nothing (frontend). *(Phase 4: empty output, RC 0; not in `node_modules/.pnpm` store.)*
- [x] `pnpm audit --audit-level moderate` exits 0 with **no** ignore list. *(Phase 4: "No known vulnerabilities found", RC 0; no `auditConfig`/ignore in package.json or .npmrc.)*
- [x] `pnpm tsc`, `pnpm test`, `pnpm build` all green. *(Phase 3: tsc clean; 266/266 tests; build 228ms.)*
- [x] All three `vitest.harness.config.ts` CI contracts green. *(Phase 3: phase13/14/24 → 63/63.)*
- [x] `dist/` has the three manual chunks and minified CSS. *(Phase 3: codemirror/react/vendor + 216.79 kB CSS.)*
- [ ] Dependabot alert #5 closed as fixed (not dismissed). *(Phase 4 verified alert #5 = esbuild / GHSA-gv7w-rqvm-qjhr / manifest `frontend/pnpm-lock.yaml`, currently `open`; auto-closes as **fixed** when the lockfile merges to `main` — deliberately NOT manually dismissed. Closes in Phase 5.)*
- [x] Build target decision documented in `vite.config.ts`. *(Phase 2: pinned `baseline-widely-available`.)*

## Rollback

Single revert of the `package.json` + `pnpm-lock.yaml` change restores the
Vite 6 tree (Phase 0 baseline). No source code is touched beyond `vite.config.ts`
/ `vitest.harness.config.ts`, both small and self-contained.

## Phase 3 result — broader harness suite (non-CI files)

The full `vitest.harness.config.ts` run (16 files, not just the 3 CI-gated)
shows 7 failing tests under Vite 8. These were measured against the Vite 6
`main` baseline and are **not regressions**:

- 3 are *identical pre-existing logic failures* on both Vite 6 and Vite 8
  (`phase6-eval-sse` T-091, `phase6-modal-accessibility` T-093,
  `stage-store` streaming-tokens) — stale contracts vs. current source.
- On Vite 6, three files **failed to even import**
  (`Failed to resolve import "@testing-library/react"`):
  `phase4-navigator-quality-badge`, `phase4-streaming-overlay`,
  `workspace-ui`. Under Vite 8 they now resolve and execute (test count
  158 → 170); `phase4-navigator-quality-badge` now **passes**, the other
  two run stale assertions that fail for their own reasons.

Net: **zero regressions** — no test green on Vite 6 fails on Vite 8, and
Vite 8 resolves one more file. Only the 3 CI-gated contracts
(phase13/14/24) gate the build; all 63 pass. Cleaning up the stale non-CI
contracts is out of scope for this CVE-removal migration.

## Phase 4 result — esbuild is gone, not suppressed

Security verification on `chore/vite8-upgrade`:

- `pnpm why esbuild` → **empty** (RC 0). esbuild is not a resolved dependency.
- `pnpm audit --audit-level moderate` → **"No known vulnerabilities found"**
  (RC 0). No `auditConfig`/ignore entry exists in `package.json` or `.npmrc` —
  the CVE is removed at the source, not masked.
- esbuild is **not** present in the `node_modules/.pnpm` store.

`grep esbuild pnpm-lock.yaml` does return 2 lines — both inside
`vite@8.0.16`'s `peerDependencies` / `peerDependenciesMeta`, where esbuild is
declared an **optional** peer (`esbuild: optional: true`): Vite 8 *permits* a
caller to bring their own esbuild but does not depend on it. Since we supply
none, nothing is resolved or installed, and no vulnerable code enters the tree.
This is the expected, correct end state — not a lingering dependency.

Dependabot alert #5 was confirmed to be exactly this advisory
(esbuild / `GHSA-gv7w-rqvm-qjhr`, manifest `frontend/pnpm-lock.yaml`) and is
currently `open`. It is **not** manually dismissed: Dependabot auto-resolves it
to **fixed** once the vulnerable version leaves the `main`-branch lockfile
(Phase 5, post-merge), satisfying the "closed as fixed (not dismissed)"
criterion.

## Out of scope / notes

- **Coverage gate is NOT part of this work.** A clean, migrated test-DB run of
  the exact CI backend command (`alembic upgrade head` + the 6 standard
  `--ignore`s + `--cov=services`) yields **1297 passed, coverage 83%** — above
  the 80% gate. The previously-cited "~78.7%" was a stale/polluted figure from
  before pytest reliably ran in CI. storyboard/pdf modules do sit low
  (storyboard_service.py 36%, pdf_export_service.py 45%, storyboard_public 53%)
  but the suite total clears 80% with margin. No action needed unless the gate
  is later raised.

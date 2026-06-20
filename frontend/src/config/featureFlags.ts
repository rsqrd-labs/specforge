/**
 * Build-time feature flags (issue #21).
 *
 * Flags are read once from Vite's statically-replaced `import.meta.env`, so the
 * bundler can tree-shake disabled branches and there is zero per-render cost.
 * Values are strings in the environment; only the exact literal `"true"` opts
 * in, so any unset/typo'd value fails closed (off).
 *
 * `branded_loaders` enables the unified `<BrandLoader>` system (the animated
 * squirrel) across every loading surface — including all generation overlays.
 * It now ships **on** by default after verification; set
 * `VITE_BRANDED_LOADERS=false` to opt back out to the legacy per-surface
 * loaders. Only the exact literal `"false"` disables it, so any unset/typo'd
 * value keeps the branded loader on.
 */
export const featureFlags = {
  brandedLoaders: import.meta.env.VITE_BRANDED_LOADERS !== "false",
} as const

export type FeatureFlag = keyof typeof featureFlags

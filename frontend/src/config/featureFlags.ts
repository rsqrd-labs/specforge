/**
 * Build-time feature flags (issue #21).
 *
 * Flags are read once from Vite's statically-replaced `import.meta.env`, so the
 * bundler can tree-shake disabled branches and there is zero per-render cost.
 * Values are strings in the environment; only the exact literal `"true"` opts
 * in, so any unset/typo'd value fails closed (off).
 *
 * `branded_loaders` dark-launches the unified `<BrandLoader>` system: it ships
 * **off** so the migrated surfaces keep their current loaders in production
 * until we flip `VITE_BRANDED_LOADERS=true` after verification.
 */
export const featureFlags = {
  brandedLoaders: import.meta.env.VITE_BRANDED_LOADERS === "true",
} as const

export type FeatureFlag = keyof typeof featureFlags

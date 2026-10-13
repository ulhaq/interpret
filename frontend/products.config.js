/**
 * Folder names of the installed packages under `src/`, for build-time tooling
 * that cannot import the app: `vite.config.ts` (pages, components) and
 * `eslint.config.js` (the boundary rules). Keep in sync with the modules listed
 * in `src/products.ts`.
 */
export const productPackages = ['interpret']

/** Optional foundation modules (billing) plus the products. */
export const modulePackages = ['billing', ...productPackages]

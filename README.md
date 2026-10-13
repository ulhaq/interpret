# SaaS Boilerplate

A production-ready starting point for multi-tenant B2B SaaS products: FastAPI + PostgreSQL backend, background worker, and a Vue 3 app.

The product-specific code lives in one package per side (`backend/src/example/`, `frontend/src/example/`). It ships as a small **Projects** feature that exercises every extension point - replace it with your product.

## Features

- **Multi-tenant** organisations with enforced tenant isolation and fine-grained RBAC (roles, permissions, API tokens)
- **Auth**: JWT access tokens + httponly refresh cookies, email verification, password reset, invites, multiple organisations per user, optional TOTP two-factor auth with recovery codes (`MFA_ENABLED` / `VITE_MFA_ENABLED`)
- **Billing** via Stripe (optional module): plans, trials, checkout, customer portal, webhooks, plan features, seat/usage/capacity limits - without it every feature is on and nothing is limited
- **Marketing endpoints** (optional module): waitlist sign-ups and the contact form the marketing site posts to
- **Audit log, GDPR export/erasure/retention**
- **Notifications**: localized transactional email (Danish/English, MJML templates) and in-app notifications
- **Observability** (opt-in, self-hosted): OpenTelemetry traces/metrics, JSON logs, browser errors via Grafana Faro, and a provisioned Grafana dashboard + alerts (Prometheus, Loki, Tempo) - see [`observability/README.md`](observability/README.md)
- **Example product**: org-scoped Projects CRUD with permissions, a plan capacity limit, a hook handler, and a worker loop

## Tech Stack

| Layer    | Stack                                                                                                                                                                                |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Backend  | Python 3.15, FastAPI, async SQLAlchemy, PostgreSQL, Alembic, `uv`                                                                                                                    |
| Worker   | Standalone asyncio process (product loops, email outbox, GDPR retention, billing's loops)                                                                                            |
| Frontend | Vue 3, TypeScript, Vite, Pinia, vue-i18n, Tailwind + Reka UI, file-based routing                                                                                                     |
| Infra    | Docker Compose (postgres, pgadmin, mailpit, backend, worker, frontend, site); opt-in profiles: `analytics` (Umami), `observability` (Alloy agent + Grafana, Prometheus, Loki, Tempo) |

## Architecture

Both sides of the codebase are split into a generic, reusable **SaaS foundation**, optional **modules** (billing; marketing on the backend) and the **product domain**, wired together by a thin assembly layer. The foundation never imports a module or the product, and they don't import each other - enforced in CI by [import-linter](https://import-linter.readthedocs.io) on the backend and ESLint `no-restricted-imports` rules on the frontend. CI also runs the tests with the optional modules removed.

```
backend/src/                            frontend/src/
├── foundation/  generic SaaS core      ├── foundation/ generic app shell
│   ├── core/    config, db, security,  │   ├── pages/ components/ stores/
│   │            hooks, entitlements    │   ├── api/ composables/ layouts/
│   ├── models/ repositories/           │   ├── locales/ types/
│   ├── services/ routers/ schemas/     │   ├── entitlements.ts navigation.ts
│   ├── templates/                      │   └── config.ts banners.ts routeGuards.ts
│   └── enums.py                        ├── billing/    optional module
├── billing/     optional module        │   └── index.ts  (manifest)
│   └── module.py  (manifest)           ├── example/    the product
├── marketing/   optional module        │   └── index.ts  (manifest)
│   └── module.py  (manifest)           ├── products.ts   installed modules
├── example/     the product            ├── brand.ts      product identity
│   └── product.py  (manifest)          ├── main.ts       assembly
├── products.py      installed modules  └── router/ plugins/ App.vue
├── bootstrap.py     composition root
├── main.py          API assembly
├── sync_permissions.py, init_db.py
```

How the two halves connect without the foundation knowing about the product:

- **Module manifest**: each module declares everything it plugs in - one `Module` per side (`src/example/product.py`, `src/billing/module.py`, `src/example/index.ts`, ...). The assembly layer reads the installed list (`src/products.py`, `src/products.ts`), so swapping the product or dropping a module is a small change on each side.
- **Hooks** (backend): lifecycle events (`MEMBER_ADDED`, `MEMBER_REMOVED`, `ORGANIZATION_CREATED`, `ORGANIZATION_DELETING`, `OWNERSHIP_TRANSFERRED`, `ENTITLEMENTS_CHANGED`) plus any a module declares and emits itself (e.g. `example.project_created`); modules list async handlers in their manifest.
- **Entitlements** (both sides): the foundation asks "is this feature on, what's this limit?" through one interface; billing answers from the organization's plan, and without billing everything is on and unlimited.
- **Composition** (backend): `bootstrap()` merges the modules' permissions, roles, audit actions, hooks, email subjects, templates and entitlements into one read-only `Composition` at startup.
- **Registries** (frontend): manifests register sidebar and settings nav items, notification presenters, dashboard banners and route guards, and set the authenticated home route; their locale trees are deep-merged in the i18n plugin.

### Two-process backend

| Process | Entry point             | Role                                                            |
| ------- | ----------------------- | --------------------------------------------------------------- |
| API     | `src/main.py` (uvicorn) | HTTP requests                                                   |
| Worker  | `worker.py`             | Every module's loops (the example heartbeat; billing's checkout cleanup, trial reminders, customer sync), the email outbox, GDPR retention |

Background loops live only in the worker so the API can scale horizontally without duplicate job runs or duplicate emails.

## Starting a new product

1. **Brand**: edit `frontend/src/brand.ts` (name, app and marketing domains) and set `APP_NAME` / `EMAIL_FROM_NAME` in `backend/.env`. Replace `frontend/public/{favicon.svg,logo.png}`.
2. **Product code**: replace the `example` package on both sides - step-by-step in [`docs/adding-a-domain-module.md`](docs/adding-a-domain-module.md).
3. **Optional modules**: keep or drop billing (no Stripe, no plans - everything unlimited) and marketing (no marketing site) - see "Keeping or dropping the optional modules" in the same guide.
4. **Plans** (with billing): adjust the seeded plans/prices/seat limits in the billing migration, product limits in your product migration, and the plan copy (`planComparisonRows`, `planDescriptions`) in the product locales.
5. **Marketing site**: `site/` (static Astro). Set the name, company details and support email in `site/src/config.ts`, the plans in `site/src/content/plans.ts`, the copy in `site/src/i18n/ui.ts` and the legal texts in `site/src/content/legal/`. `SITE_THEME` picks one of eight designs at build time (editorial, tech, soft, swiss, brutal, enterprise, nordic, aurora), and `PUBLIC_CTA_MODE=waitlist` switches every call to action to the waitlist for a pre-launch. The app links to its terms and privacy pages (`LEGAL_PATHS` in `frontend/src/foundation/constants.ts`) and to its `/og-image.png`.
6. **Deploy config**: `Caddyfile.example` (marketing domain -> site, `app.` subdomain -> app), `ANALYTICS_ORIGIN` in `docker-compose.yml` (only with the `analytics` profile), the deploy path in `.github/workflows/ci.yml`.

Architecture details live in `backend/CLAUDE.md` and `frontend/CLAUDE.md`.

## Getting Started

### Docker Compose (recommended)

```bash
cp backend/.env.example backend/.env   # fill in secrets (APP_SECRET, DB_*, ...)
make up-local                          # postgres, mailpit, pgadmin, backend, worker, frontend
make logs                              # tail everything
make down                              # stop
```

| Service                | URL                   |
| ---------------------- | --------------------- |
| Frontend               | http://localhost:5173 |
| API (+ OpenAPI docs)   | http://localhost:8000 |
| Mailpit (caught email) | http://localhost:8025 |
| pgAdmin                | http://localhost:5050 |

### Without Docker

Run each in its own terminal:

```bash
# 1 - backend API
cd backend && uv run poe dev

# 2 - background worker
cd backend && uv run python worker.py

# 3 - frontend (proxies /v1 -> localhost:8000)
cd frontend && npm run dev
```

Database setup and seeding (migrations, permission sync, demo organizations/users/roles; plans come from the billing migration):

```bash
cd backend && python -m src.init_db
```

## Development

### Backend (`cd backend`, package manager: `uv`)

```bash
uv run poe dev      # dev server on :8000
uv run poe fix   # ruff format + autofix
uv run poe check     # ty (type check) + ruff + import-linter boundary/layer contracts
uv run poe test     # pytest against PostgreSQL (see below)
uv run poe test-foundation-only   # the same without the optional modules (CI runs both)
alembic revision --autogenerate -m "..."   # new migration
alembic upgrade head
```

Tests run against the app's PostgreSQL server (the `DB_*` settings in `.env`, or
`DB_CONNECTION` if set, as in CI), but never touch the app database: each
pytest-xdist worker creates and drops its own `<db>_test_<worker>` database, so
`DB_USER` needs `CREATEDB`. The dev stack
grants it when the postgres volume is first initialized (`DB_USER_CREATEDB` in
`docker-compose.dev.yml`); production doesn't. With the dev stack up, run
`uv run poe test` from `backend/`. Without a `DB_CONNECTION` (only compose and CI
set one), the app settings build it from the `DB_*` parts and connect to
`localhost` on `POSTGRES_PORT` (default 5432; set it when using a
`make up-local <offset>` stack) - this also covers `alembic`, `init_db` and the
dev server run on the host. Only with `APP_ENV=local`.

### Frontend (`cd frontend`)

```bash
npm run dev         # vite dev server on :5173
npm run typecheck   # vue-tsc -b (needs the types `dev`/`build` generate)
npm run lint        # eslint --fix (includes the foundation/product boundary rule)
npm run gen:api     # regenerate the API types from ../backend/openapi.internal.json
npm run build       # production build (SPA)
npm test            # component tests (vitest)
npm run format      # prettier (CI checks it)
npm run test:e2e    # playwright (needs the dev stack running)
```

Routes are file-based: adding a page under `src/foundation/pages/` or a module's `pages/` (`src/billing/`, `src/example/`) creates a route. Components in every `components/` root are auto-registered.

### Key backend conventions

- **Layering**: routers → services → repositories → models; services raise `ClientException(ErrorCode.X)`, middleware renders consistent JSON errors.
- **Tenant isolation**: repositories extending `OrganizationScopedRepository` refuse unscoped queries unless `.unscoped` is used explicitly.
- **Permissions**: `Permission` (foundation), module and product StrEnums (`ExamplePermission`), merged by `bootstrap.py` and synced into the database on every deploy (`python -m src.sync_permissions`, which also grants them to every Owner); guard routes with `require_permission(...)` and frontend UI with `<PermissionGuard>` / `hasPermission()`.

### Key frontend conventions

- **Stores are the data gateway**: components never import `api/*` modules directly; every read/write goes through a Pinia store action.
- **i18n everywhere**: all user-facing strings come from `vue-i18n` (`da` default, `en`), foundation and product locale trees merged at startup.

## Repository Layout

```
├── backend/         FastAPI API + worker (see backend/CLAUDE.md)
├── frontend/        Vue 3 SPA - the signed-in app (see frontend/CLAUDE.md)
├── docs/            adding-a-domain-module.md + operational runbooks
├── scripts/         db-init / db-backup / db-restore
├── docker-compose.yml (prod) / docker-compose.dev.yml (local dev, used by Makefile)
└── Makefile         up / up-local / down / logs / shell-backend / shell-worker
```

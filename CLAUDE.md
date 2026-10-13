# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Product

**SaaS Boilerplate** - a multi-tenant B2B SaaS starter: auth, organizations, RBAC, Stripe billing with plan limits, audit log, GDPR tooling, email + in-app notifications, plus a static marketing site.

Product-specific code lives in one package per side - `backend/src/interpret/` and `frontend/src/interpret/`: **Interpret**, spoken interpretation for Danish kommuner, hospitals and clinics. A staff member and a citizen share one device; each holds their own button and speaks, and the other side reads and hears the translation (Danish ⇄ English, Arabic, Ukrainian). The app records 16 kHz mono WAV in the browser (`useWavRecorder`); `POST /v1/interpret/conversations/{id}/turns` runs speech-to-text → translation → text-to-speech through the providers in `src/interpret/provider/` (`live`: Azure Speech + Claude; `fake`: canned text for local dev and tests, `INTERPRET_PROVIDER`). **Nothing said is stored** - only conversation metadata (languages, turn count, speech duration); keep it that way. Permissions `use:interpret`, `read:interpret_usage`; plan limit `interpret_turns` per period. Some docs below still use the removed `example` package as their illustration.

Starting a new product from this template:

- Replace/rename the `example` package on both sides - see `docs/adding-a-domain-module.md`.
- Keep or drop the optional modules (billing, marketing) - see "Keeping or dropping the optional modules" in the same guide.
- Set the product identity in `frontend/src/brand.ts` (name, app and marketing domains) and `APP_NAME` / `EMAIL_FROM_*` in `backend/.env`.
- Adapt plan seeds (billing migration + product migration), and plan copy (`planComparisonRows` / `planDescriptions` in the product locales). Mirror plan and brand changes in the marketing site (`site/src/config.ts`, `site/src/content/plans.ts`); the app links to its terms/privacy pages (`LEGAL_PATHS` in `frontend/src/foundation/constants.ts`).
- Replace `frontend/public/{favicon.svg,logo.png}`.

## Repository Structure

Full-stack multi-tenant SaaS:

- `backend/` - FastAPI + Python, PostgreSQL, async SQLAlchemy, Alembic migrations. Billing (plans, subscriptions, Stripe) and marketing (the waitlist and contact-form endpoints) are optional modules, `backend/src/billing/` and `backend/src/marketing/`. See `backend/CLAUDE.md`.
- `frontend/` - the signed-in app: Vue 3 + TypeScript SPA, Vite, Pinia, file-based routing. See `frontend/CLAUDE.md`.
- `site/` - the marketing site (landing, features, pricing, about, contact, legal pages): standalone static Astro site, da/en. See `site/CLAUDE.md`.

The backend and frontend are each split into a generic SaaS **foundation** package,
optional modules (**billing** on both sides, **marketing** on the backend) and the
**product** package (`src/foundation/` + `src/billing/` + `src/example/`), wired
together by a thin assembly layer driven by a module manifest list
(`src/products.py` / `src/products.ts`). The foundation never imports a module or the
product, and the modules and the product don't import each other - enforced by
import-linter (backend) and ESLint (frontend).

## Running Locally

**Recommended: Docker Compose** (runs postgres, redis, mailpit, backend, worker, frontend and site together):

```bash
cp backend/.env.example backend/.env   # fill in secrets
make up-local                          # starts all services + pgadmin + mailpit
make up-local 1                        # port offset: adds 1 to every host port (for parallel git worktree stacks)
make down                              # stop everything
make logs                              # tail all logs
```

Services: backend API on `:8000`, app on `:5173`, marketing site on `:4321`, pgadmin on `:5050`, mailpit UI on `:8025`.

**Without Docker** (run each in a separate terminal, `cd` first):

```bash
# Terminal 1 - backend API
cd backend && uv run poe dev

# Terminal 2 - background worker (product loops, GDPR retention, billing cleanup)
cd backend && uv run python worker.py

# Terminal 3 - app
cd frontend && npm run dev

# Terminal 4 - marketing site (optional)
cd site && npm run dev
```

The frontend and site dev servers proxy `/v1` → `localhost:8000`.

## Two-Process Backend Architecture

The backend runs as **two separate processes**:

| Process    | Entry point             | What it does                                                                                                                      |
| ---------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **API**    | `src/main.py` (uvicorn) | Handles HTTP requests                                                                                                             |
| **Worker** | `worker.py`             | Runs product loops (the example heartbeat), the email outbox, GDPR retention, and billing's loops (stale checkout cleanup, trial reminders, customer sync) as concurrent asyncio tasks |

Adding a new background loop: implement a `run_X_loop(session_factory)` coroutine and add it to `worker_loops` in the product's manifest (`src/example/product.py`); `worker.py` starts every listed loop. Wrap each iteration in `track_worker_run("x", interval)` (`backend/src/foundation/core/telemetry.py`) so it shows up on the dashboard and in the overdue/failing alerts, and start the iteration's transaction with `if await try_job_lock(session, "x"):` (`backend/src/foundation/core/database.py`) so it runs in one worker at a time even when workers overlap - skip that only for a job that is safe to run concurrently. Never start background tasks inside `main.py`'s lifespan - horizontal API scaling would cause duplicate runs.

## API Types (Backend → Frontend)

The frontend's API types are generated from the backend's schema, not hand-written: after changing a backend request/response model or route, run `cd backend && uv run poe openapi`, then `cd frontend && npm run gen:api`, and commit `backend/openapi.internal.json` (every route), `backend/openapi.json` (the public schema) and `frontend/src/api-schema.ts`. CI fails when they are stale; the pre-commit hook regenerates and stages all three when backend code changes. Details: `frontend/CLAUDE.md` ("API types are generated").

## Permission Flow (Backend → Frontend)

Foundation permissions are a `Permission` StrEnum in `backend/src/foundation/enums.py`; product permissions are `ExamplePermission` in `backend/src/example/enums.py`. The composition root (`backend/src/bootstrap.py`) merges them (with billing's) into `ALL_PERMISSIONS` and the seeded `DEFAULT_ROLES`. Permissions are not seeded by migrations: `python -m src.sync_permissions` (run on every deploy after `alembic upgrade head`, and by `init_db`) adds the declared ones the database lacks and grants them to every Owner role, so a new permission needs no migration. At login, the API returns the user's flattened permission list; the frontend stores it in `stores/auth.ts` and checks it via `hasPermission()` / `usePermission()` / `<PermissionGuard>`.

When adding a new permission-gated feature:

1. Add the enum value: foundation features in `backend/src/foundation/enums.py`, product features in `backend/src/example/enums.py`
2. Add a human-readable description to the `PERMISSION_DESCRIPTIONS` / `EXAMPLE_PERMISSION_DESCRIPTIONS` map in the same file
3. Assign it to the appropriate default roles (`DEFAULT_ROLES` / `EXAMPLE_DEFAULT_ROLE_PERMISSIONS`)
4. Guard the backend route with `require_permission(Permission.X)`
5. Guard frontend UI with `<PermissionGuard permission="x:y">` or `hasPermission('x:y')`

## Email / Notifications

Outbound email uses SMTP (mailpit in local dev).
Templates live in `backend/src/foundation/templates/` (foundation emails) and the modules' own `templates/` (`backend/src/billing/templates/`, `backend/src/marketing/templates/`, whose MJML includes the foundation's shared partials); edit the MJML source in `emails/mjml/<locale>/` and compile it from that `templates/emails/` with `npx mjml@4 mjml/<locale>/<name>.mjml -o <locale>/<name>.html`, which reproduces the committed HTML exactly; add the subject to both locales in `services/email_content.py`, or the module's `emails.py` for a module's (`src/billing/emails.py`, with its UTM medium in `BILLING_EMAIL_CAMPAIGNS`; `src/marketing/emails.py`) and an optional product `templates/` directory (product emails, declared in the product manifest and registered by `bootstrap()`). Email that reports a change made inside a transaction (webhooks, worker jobs) is queued with `queue_email` (`services/email_outbox.py`) and sent by the worker's outbox loop after commit, with retries - never call `send_email` while holding a transaction open. Emails from a request go out after it commits via `BackgroundTasks`. SMTP calls are bounded by `EMAIL_TIMEOUT_SECONDS` and run in a thread (`asyncio.to_thread`) so they don't block the event loop. Billing's emails go to subscription managers when billing emits a `BillingHookEvent` (webhook handlers, the trial reminder loop), through `BILLING_NOTIFICATION_RULES` in `src/billing/emails.py` (one rule per event: template, category, the event kwargs it shows); each also writes an in-app notification per recipient, in the same transaction: type `billing.<email template>`, shown in the bell and on the notifications page by the presenters in `frontend/src/billing/notifications.ts` - add one there (with en/da copy under `notifications.billing`) when adding a billing email, alongside its event and rule. Product notifications register their own presenters (`registerNotificationPresenter`).

**Realtime events** make the app's notification badge live: `publish_to_user(session, user_id, RealtimeEvent(...))` (`backend/src/foundation/core/realtime.py`) sends an event to the user's open tabs once the transaction commits (`after_commit` in `core/database.py`; dropped on rollback). Redis pub/sub (`REDIS_URL`, required outside `APP_ENV=local`) carries it from the worker or any API replica to the API process holding the user's stream, `GET /v1/events` (Server-Sent Events, closed after `REALTIME_STREAM_MAX_SECONDS` so it never outlives its access token). Delivery is best effort, so events are hints, not data: the app re-fetches on each event and whenever the stream (re)connects or receives `resync`. `deliver_notification` publishes `notification.created` and marking read publishes `notification.read` (`NotificationEvent`). In the app, `stores/realtime.ts` keeps the stream open while signed in (reconnect with backoff, token refresh, paused in a long-hidden tab); a feature subscribes with `on(type, handler)` and `onSync(handler)`, as `stores/notifications.ts` does.

Users choose per **notification category** which they receive in-app and by email (Settings → Notifications, `GET/PATCH /v1/notifications/preferences`, stored per user in `notification_preference`; no row means the category's defaults). A module lists its category keys in a `StrEnum` (like its permissions) and declares the categories in its manifest (`notification_categories`: key, default channels, `email_required` for account-critical email that can't be turned off, an optional `permission` limiting who is offered it) and sends them either declaratively - a `NotificationRule` in the manifest's `notification_rules` (event, category, notification type, email template, the permission recipients hold, an event kwarg naming a user to skip, the event kwargs copied into the payload/email data, email-only links), which the foundation's notification service subscribes to the event, so the emitting code knows nothing about notifications (see `src/example/emails.py`) - or, for recipients a rule can't express, from code with `deliver_notification` (`services/notification.py`), which writes the in-app notification and/or queues the email according to the recipient's choice; label a category in the app under `notificationPreferences.categories.<key>` (en + da). Billing's three are `BillingNotificationCategory` (`src/billing/enums.py`: trial, payment - email required, subscription); their declarations and the rules are in `src/billing/emails.py`. A `date` in a rule's data is stored as an ISO string in the in-app payload and written in each recipient's locale in the email. Foundation emails (verification, password reset, invites, security notices) are transactional and not subject to preferences.

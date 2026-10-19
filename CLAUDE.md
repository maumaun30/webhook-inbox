# CLAUDE.md

## Project
Webhook Inbox — capture, inspect, verify and replay webhooks. Personal dev tool for debugging
integrations (Maya payments, Shopify, HubSpot forms, Aiosell channel manager, GitHub).

## Stack
FastAPI · SQLModel · Jinja templates · Postgres via psycopg 3 (Supabase) · SQLite fallback locally.
Deploy target: Vercel (Python runtime, `tool.vercel.entrypoint = "app.main:app"`) + Supabase free tier.

## Layout
- `app/main.py` — routes: public capture `/hook/{source}`, admin JSON API `/api/hooks*`,
  dashboard `/` and `/h/{id}`, `/api/cron/keepalive`, `/healthz`
- `app/models.py` — single `Hook` table
- `app/db.py` — engine (NullPool + `prepare_threshold=None` for Supabase transaction pooler),
  lazy `create_all` on first request
- `app/signatures.py` — Shopify, HubSpot v3, generic hex HMAC; secret per source via `SECRET_<SOURCE>`
- `app/auth.py` — HTTP Basic, password = `ADMIN_TOKEN`; open locally if unset, 503 on Vercel
- `scripts/replay_local.py` — pull a hook from the deployed inbox, send to localhost
- `vercel.json` — cron hits keepalive every 3 days (Supabase pauses free projects after 1 week idle)

## Commands
```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload
pytest
```

## Constraints
- Vercel filesystem is ephemeral → no SQLite in production.
- Vercel request body limit ~4.5 MB → capture caps at 4 MB.
- Webhook providers time out fast → keep `/hook/{source}` minimal (store and return 200).
- Always store payloads, even with invalid signatures; signature result is a tag, not a gate.

## Status
- Done: capture, list/search/filter, detail, replay (API, dashboard, local script), delete,
  signature checks, auth, keepalive cron. 10 tests pass.
- Deployed: https://webhook-inbox-opal.vercel.app (Vercel project `webhook-inbox`, region `sin1`,
  GitHub-connected: push to `main` deploys prod). DB: Supabase project `webhook-inbox`
  (ref `wxlywphdnmcpdvikudpj`, ap-southeast-1, pooler host `aws-0-ap-southeast-1`).
  Smoke-tested 2026-10-19: capture, auth, dashboard, replay, cron keepalive.
- Keep Vercel region next to Supabase region; cross-region adds ~seconds per request.

## Next steps (suggested)
1. Set `SECRET_<SOURCE>` env vars in Vercel for sources that sign payloads; point providers at
   `/hook/<source>`.
2. Retention: delete hooks older than N days (run from the keepalive cron) to stay under 500 MB.
3. Optional: Telegram/email alert on `invalid` signatures; per-source "auto-forward to URL".

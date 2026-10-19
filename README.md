# Webhook Inbox

Capture, inspect, verify and replay webhooks (Maya, Shopify, HubSpot, Aiosell, GitHub…).
FastAPI · SQLModel · Postgres (Supabase) · deploys to Vercel.

## Endpoints

| Route | Auth | Purpose |
|---|---|---|
| `ANY /hook/{source}` | public | Capture a webhook. `source` = `a-z0-9-`, e.g. `/hook/maya` |
| `GET /` · `GET /h/{id}` | admin | Dashboard: list, filter, search, detail, replay |
| `GET /api/hooks?source=&q=&limit=` | admin | List (JSON) |
| `GET /api/hooks/{id}` | admin | Full payload |
| `POST /api/hooks/{id}/replay` `{"target_url": "..."}` | admin | Re-send with same method, headers, body |
| `DELETE /api/hooks/{id}` | admin | Delete |
| `GET /api/cron/keepalive` | `CRON_SECRET` | Keeps Supabase awake; deletes hooks older than `RETENTION_DAYS` (default 30, `0` = keep all) |

Admin = HTTP Basic, any username, password = `ADMIN_TOKEN`.

## Signature checks

Set `SECRET_<SOURCE>` (e.g. `SECRET_SHOPIFY`). Each hook is tagged `valid` / `invalid` / `unchecked`;
payloads are always stored.

- Shopify — `X-Shopify-Hmac-Sha256`
- HubSpot v3 — `X-HubSpot-Signature-v3` (+ 5-min timestamp window)
- Generic hex HMAC-SHA256 — `X-Hub-Signature-256` (GitHub) or `X-Signature`

Providers without a signature header (e.g. Maya) are stored as `unchecked`.

## Local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload        # SQLite at ./local.db, no auth when ADMIN_TOKEN unset
pytest
```

## Deploy (Vercel + Supabase)

1. **Supabase** → new project → *Connect* → copy the **Transaction pooler** string (port 6543).
   Tables are created automatically on first request.
2. **Vercel** → import this repo (FastAPI is auto-detected via `tool.vercel.entrypoint`).
3. Set env vars: `DATABASE_URL`, `ADMIN_TOKEN`, `CRON_SECRET`, any `SECRET_<SOURCE>`.
4. Deploy, then point webhooks at `https://<app>.vercel.app/hook/<source>`.

`vercel.json` runs `/api/cron/keepalive` every 3 days so the free Supabase project never hits
its one-week inactivity pause.

## Replaying to localhost

Vercel can't reach your machine. Either replay to a public URL (staging / tunnel) from the
dashboard, or pull and send locally:

```bash
INBOX_URL=https://<app>.vercel.app ADMIN_TOKEN=... \
  python scripts/replay_local.py 42 http://localhost:8000/webhooks/shopify
```

## Limits

- Max body 4 MB (Vercel request limit is ~4.5 MB).
- Replay strips hop-by-hop and platform headers (`host`, `x-vercel-*`, `x-forwarded-*`, `cf-*`)
  and adds `x-replayed-from`.
- Signature-checked replays still carry the original signature, so the target's own
  verification passes only if it uses the same secret.

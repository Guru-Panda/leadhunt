# LeadHunt

Multi-tenant outbound lead-generation tool. Autonomously hunts prospects matching each user's ICP across 10+ free data sources AND discovers new sources on its own using an LLM-powered discovery agent.

**Goal:** 100+ leads/day per user, fully free, ~60% with verified emails.

## Stack

- **Frontend:** React 18 + Vite + TypeScript + TailwindCSS + React Router 6 + TanStack Query + Recharts
- **Backend:** FastAPI + SQLAlchemy 2.0 (`Mapped[]`) + Pydantic v2 + APScheduler + httpx + selectolax
- **DB:** PostgreSQL (Railway) or SQLite (local dev)
- **LLM:** Groq API — `llama-3.1-8b-instant` (fast) + `llama-3.3-70b-versatile` (HQ)
- **Auth:** JWT (30-min access + 7-day refresh) + email OTP via Gmail SMTP
- **Hosting:** Railway (backend + db) + Vercel (frontend)

## Architecture

```
backend/
  main.py            # FastAPI app + APScheduler lifespan
  config.py          # Pydantic Settings, all env vars optional with dev defaults
  database.py        # SQLAlchemy engine, SQLite/Postgres autodetect
  models.py          # User, Strategy, Lead, DiscoveredSource, SyncRun, EmailOTP
  auth.py            # JWT helpers
  email_service.py   # OTP delivery via aiosmtplib (graceful dev fallback)
  llm.py             # Groq client + JSON-tolerant parser
  routers/
    auth.py          # signup, OTP, login, refresh, me
    strategy.py      # CRUD + analyze + sync-now
    leads.py         # list, filter, csv-export, status, outreach, re-enrich
    monitor.py       # source-stats, sync-runs, discovered-sources, add-custom-url, discover
    analytics.py     # stat cards + chart data
  pipeline/
    icp_translator.py    # freeform → structured ICP via Groq
    scorer.py            # lead intent scoring (Groq, source-signal-aware)
    discoverer.py        # LLM finds NEW lead sources beyond the base set
    universal_extractor.py # parse any URL + extract leads via LLM
    outreach.py          # personalized cold email from source_snippet
    cron.py              # sync_strategy, hourly_sync, daily_retention_cleanup
  sources/             # 12 base sources, each exposes fetch(icp_params, limit)
    github.py
    hackernews.py        # Algolia + Who-is-hiring thread
    producthunt.py       # GraphQL
    ycombinator.py       # Algolia (auto-rotating key) + founder scrape
    reddit.py            # public .json (no OAuth)
    indeed.py            # graceful Cloudflare-block degrade
    wellfound.py         # graceful Cloudflare-block degrade
    remoteok.py          # public JSON
    google_cse.py        # Google Custom Search (LinkedIn)
    bing.py              # Mojeek (DDG blocked)
    whois_rdap.py        # registrant lookup (used in enrichment)
    companies_house.py   # UK officers (free auth required)
  enrichment/
    extractors.py        # email regex + company-site mailto scrape
    email.py             # 5-tier email discovery chain w/ provenance tracking

frontend/
  src/
    App.tsx              # routes
    context/AuthContext  # JWT state
    api/                 # typed axios methods
    components/
      Layout.tsx         # purple sidebar
      SourceBadge.tsx    # per-source color chip
      TagInput.tsx       # array-of-string editor
    pages/
      LoginPage / SignupPage   # OTP flow with dev fallback
      StrategyPage             # ICP form + Groq-extracted chips
      LeadsPage                # filter table + drawer + outreach + CSV
      MonitorPage              # per-source health + discovered sources + custom URL
      AnalyticsPage            # stat cards + Recharts
```

## Quick start (local)

### Backend
```bash
cd LeadHunt
pip install -r requirements.txt

# Create .env (all optional — boots with zero config)
echo "GROQ_API_KEY=gsk_..." > .env

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Boots on SQLite (`./leadhunt.db`). In dev mode (default), OTPs are surfaced in the signup/login API response and logged to console — no SMTP needed.

### Frontend
```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 — Vite proxies /api to localhost:8000
```

## Environment variables

| Var | Required | Notes |
|---|---|---|
| `GROQ_API_KEY` | strongly recommended | https://console.groq.com/keys — without it ICP/scoring/discovery all skip |
| `SECRET_KEY` | prod | Random 32+ chars. Auto-generated in dev. |
| `DATABASE_URL` | prod | `postgresql://...` on Railway. Defaults to `sqlite:///./leadhunt.db` locally. |
| `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | prod | Gmail App Password. Without these, dev mode surfaces OTP in API response. |
| `GITHUB_TOKEN` | optional | Free PAT, 5000 req/hr. Enables GitHub user/org/email source. |
| `REDDIT_*` | NOT needed | Reddit source uses public `.json` (no OAuth). |
| `PRODUCTHUNT_TOKEN` | optional | OAuth bearer for ProductHunt GraphQL. |
| `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | optional | 100 free queries/day. LinkedIn profile discovery. |
| `HUNTER_API_KEY` | optional | 25 free searches/mo. Auto-fires when name+domain known. |
| `COMPANIES_HOUSE_KEY` | optional | Free signup for UK officer data. |
| `FRONTEND_URL` | prod | CORS allow-list. |
| `LEAD_RETENTION_DAYS` | optional | Default 90. |

## Production deploy

### Backend → Railway

1. Push this repo to GitHub.
2. New project on https://railway.app → **Deploy from GitHub repo** → select repo.
3. Add a **Postgres plugin** → it injects `DATABASE_URL`.
4. Add env vars: `GROQ_API_KEY`, `SECRET_KEY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `FRONTEND_URL`, plus any optional source keys.
5. Railway reads `railway.toml`, builds with nixpacks, runs `uvicorn backend.main:app`, health-checks `/health`.

### Frontend → Vercel

1. Same repo on https://vercel.com → **Import Project**.
2. **Root Directory:** `frontend`.
3. **Build Command:** `npm run build`, **Output:** `dist`.
4. Env var: `VITE_API_URL` = your Railway backend URL.
5. `vercel.json` rewrites `/api/*` → Railway in production.

## How leads flow

1. User creates a Strategy (free-form `main_problem` + `ideal_customer`).
2. **ICP Translator** (Groq 70B) converts it into structured search params (roles, industries, queries).
3. **Source Discovery Agent** (Groq 70B, weekly) suggests 15 NEW lead sources beyond the base 12, validates each.
4. **Hourly cron** runs each base source + top 20 discovered sources:
   - Each source returns lead drafts → **enrichment chain** finds emails (source text → company site → WHOIS → GitHub commits → Hunter → pattern guess) → **scorer** (Groq) rates 0-1 → saved if score ≥ `intent_threshold`.
5. **Outreach generator** (on-demand) writes a personalized cold email using the lead's actual `source_snippet`.
6. **Daily cleanup** (03:00 UTC) deletes leads older than `LEAD_RETENTION_DAYS`.

## Email provenance

Every saved lead carries `email_source` ∈ `{source_text, company_site, github_commit, whois, hunter, hunter_verified, pattern_guess}` — the UI shows a color-coded confidence pill so you know whether to trust the address.

`hunter` (found via Hunter.io email-finder) and `hunter_verified` (a pattern guess confirmed valid by Hunter's verifier) are the highest-confidence sources. Hunter usage is quota-guarded against the free tier (25 searches + 50 verifications/month) — set `HUNTER_API_KEY` to enable.

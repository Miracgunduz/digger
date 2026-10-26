# Opportunity Hunter

This was an earlier project of mine before [intern-opportunity-tracker](https://github.com/Miracgunduz/intern-opportunity-tracker) — same general idea, but scanning Reddit for indie/side-project ideas instead of career opportunities. I'm actively developing intern-opportunity-tracker now; this one still runs but isn't getting new features.

A bot that scans Reddit twice a day, analyzes indie/side-project ideas with AI, and sends the results to Telegram as an instant digest — running entirely on free infrastructure.

## What it does

- Scans 10 selected subreddits (`SideProject`, `startups`, `Entrepreneur`, `micro_saas`, etc.)
  via Reddit's authentication-free RSS endpoints.
- Analyzes the posts it finds with Google Gemini; for each idea it extracts a summary,
  reasoning, a technical-difficulty score, required technologies, competitor analysis, and a
  target-audience/monetization suggestion.
- Sends the result to Telegram as a formatted digest.
- Runs automatically twice a day (09:00 / 21:00); can also be triggered instantly via
  Telegram commands.

## Commands

| Command | Description |
|---|---|
| `/tara` | Start an on-demand scan right now |
| `/rakipbul <idea>` | Competitor and market-gap analysis for a given idea |
| `/maliyet <idea>` | First-6-months infrastructure cost + suggested minimum subscription price |
| `/trendler` | Scan of the last week's complaints/opportunities |
| `/help` | Command list |

## Architecture

Built entirely on serverless, free-tier infrastructure:

- **GitHub Actions** — scheduled scans (`schedule`) and command execution
  (`workflow_dispatch`), making the Reddit RSS + Gemini calls with unlimited outbound network access.
- **Cloudflare Workers** — instantly handles the Telegram webhook, responds directly to
  commands like `/help`, and delegates heavier work to GitHub Actions.
- **Google Gemini (free tier)** — idea analysis, competitor research, cost estimation.
- **Telegram Bot API** — notification and command interface.

No long-running server or polling loop — each trigger does its job and exits.

```
Telegram message → Cloudflare Worker (instant) → GitHub Actions workflow_dispatch → Reddit RSS + Gemini → Telegram digest
```

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in your own keys
   (`GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `REDDIT_USER_AGENT`).
3. Add the same values to your GitHub repo under **Settings → Secrets and variables → Actions**.
4. Deploy `worker/telegram-webhook.js` to Cloudflare Workers and set the required environment
   variables (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `WEBHOOK_SECRET`, `GH_PAT`,
   `GH_REPO`, `GH_WORKFLOW_FILE`).
5. Connect the webhook to the Worker with a Telegram `setWebhook` call.

## Technical notes

- Uses Reddit's authentication-free `.rss` / `search.rss` endpoints instead of the official
  API; automatic backoff/retry handles rate limits.
- Gemini responses are requested as structured JSON via `response_mime_type: application/json`.
- Telegram's legacy Markdown parser is fragile, so sends automatically fall back to plain text
  on failure.

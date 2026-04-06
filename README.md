# Minty Cards Arbitrage Agent

Scans eBay, TCGPlayer, and PriceCharting every 30 minutes.
Fires Telegram alerts with one-click buy links when deals are found.

## Files in this folder
- app.py — the agent
- requirements.txt — dependencies
- Procfile — start command
- render.yaml — Render config

## Deploy to Render (5 min)

1. Go to github.com — create a free account if you don't have one
2. Click the + icon → New Repository
3. Name it: minty-cards-agent
4. Make it Public → Create
5. Click "uploading an existing file"
6. Drag ALL 4 files from this folder into the upload area
7. Click "Commit changes"
8. Go to render.com → New → Web Service
9. Connect your GitHub account → select minty-cards-agent repo
10. Render auto-detects everything — just hit Deploy
11. Wait ~3 min for it to build
12. Once live, visit: https://your-app.onrender.com/test-telegram
13. You'll get a Telegram message confirming it works
14. Agent hunts every 30 min automatically from here on

## Endpoints
- /status — current agent status
- /deals — all current deals as JSON
- /log — last 100 log entries
- /hunt — trigger a manual hunt
- /test-telegram — send a test Telegram message

---
title: DealDesk Agent API
emoji: 🏠
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# DealDesk Agent API

LangGraph sales agent for real-estate agencies and car dealers.

- `POST /chat` body `{"user_id": "...", "thread_id": "...", "message": "..."}`
- `GET /health` returns `ok`

Set these Space secrets: `ANTHROPIC_API_KEY`, `DATABASE_URL`, `ADMIN_SECRET`, `CORS_ORIGINS`.
See the main repository README for the full documentation.

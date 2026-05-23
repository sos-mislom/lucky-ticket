# Architecture

## Monorepo Layout

```text
apps/
  web/        React web client
  tg-bot/     Telegram bot entrypoint
  vk-bot/     VK bot entrypoint
  android/    Android client boundary
backend/
  app/api/        FastAPI routes and schemas
  app/tickets/    OCR text parsing and ticket normalization
  app/happiness/  happiness scoring rules
  app/fiscal/     official receipt provider integrations
  app/db/         SQLAlchemy models
  tests/          backend tests
infra/            local and deployment infrastructure
docs/             product and technical decisions
```

## Backend Boundaries

The backend owns all persistent product state. Bots and clients should stay thin: they upload media, show results, and poll or receive notifications.

The first domain boundaries are:

- tickets: file upload, OCR output, parser templates;
- happiness: deterministic scoring rules and curated number dictionary;
- fiscal: official receipt provider checks;
- leaderboard: daily and global aggregates;
- profiles: public user card themes.

## Verification Policy

The system may store ticket numbers, fiscal ticket series, route, date, and card masks already printed on user-provided receipts. It must not store full bank card numbers, CVV codes, PINs, or bank credentials.

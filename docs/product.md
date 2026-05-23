# Product Notes

## User Story

A user sends a public transport ticket photo, PDF, or electronic receipt. The system extracts the ticket number, scores its happiness, puts it into the user's day chart immediately, and marks it as verified after the official fiscal receipt check succeeds.

## Surfaces

- Telegram bot: fastest upload and notifications.
- Web app: profile, leaderboard, public card designer.
- VK bot: social network entrypoint.
- Android app: camera-first experience and future NFC/notification helpers.

## MVP

1. Upload ticket image or paste OCR text.
2. Extract ticket number, date, route, price, fiscal series.
3. Score happiness deterministically.
4. Save as `pending_check`.
5. Retry official receipt lookup after one day.
6. Show daily chart and global leaderboard.
7. Let users tune a profile card theme.

## Ticket Statuses

- `uploaded`: file is stored.
- `parsed`: fields were extracted.
- `scored`: happiness score is available.
- `pending_check`: official fiscal receipt is not verified yet.
- `verified`: official receipt was found.
- `rejected`: official receipt was not found after retry window.
- `manual_review`: confidence is too low or fields conflict.

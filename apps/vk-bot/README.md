# VK Bot

Thin VK entrypoint for the backend API.

MVP actions:

- receive ticket photo/document;
- call backend upload/parse endpoints;
- return score and verification status;
- show global top.

## Run

Set environment variables:

```env
VK_BOT_TOKEN=...
BACKEND_URL=http://127.0.0.1:8000
PUBLIC_WEB_URL=http://127.0.0.1:8000
```

`VK_GROUP_ID` is optional: the bot tries to detect the group from the token. If VK returns a group lookup error, set the numeric group id explicitly.

```powershell
python apps/vk-bot/bot.py
```

In VK group settings, messages and Long Poll API must be enabled for the bot token.

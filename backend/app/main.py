import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.routes import router
from app.core.settings import get_settings
from app.db.session import init_db
from app.jobs.ticket_checks import pending_ticket_check_loop
from app.jobs.ticket_mail import ticket_mail_configured, ticket_mail_loop


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    ticket_check_task: asyncio.Task[None] | None = None
    ticket_mail_task: asyncio.Task[None] | None = None
    init_db()
    if settings.ticket_check_interval_seconds > 0:
        ticket_check_task = asyncio.create_task(
            pending_ticket_check_loop(settings.ticket_check_interval_seconds)
        )
    if ticket_mail_configured(settings) and settings.ticket_mail_poll_interval_seconds > 0:
        ticket_mail_task = asyncio.create_task(
            ticket_mail_loop(settings.ticket_mail_poll_interval_seconds)
        )
    try:
        yield
    finally:
        for task in [ticket_check_task, ticket_mail_task]:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="API сервиса счастливый билетик",
        lifespan=lifespan,
    )
    app.include_router(router, prefix="/api")

    web_dist = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app


app = create_app()

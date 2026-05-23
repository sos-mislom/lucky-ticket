from collections.abc import Iterator
import secrets

from sqlalchemy import inspect, text
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import get_settings
from app.db.models import Base, Ticket, TicketHappiness, make_ticket_mail_code
from app.happiness.rules import score_ticket_number


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args=_connect_args(settings.database_url),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _apply_lightweight_migrations()
    _refresh_happiness_translations()


def _apply_lightweight_migrations() -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    with engine.begin() as connection:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "is_profile_public" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN is_profile_public BOOLEAN NOT NULL DEFAULT 1")
            )
        if "personal_data_consent_given" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN personal_data_consent_given BOOLEAN NOT NULL DEFAULT 0")
            )
        if "access_token" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN access_token VARCHAR(64)"))
            user_rows = connection.execute(text("SELECT id FROM users")).mappings()
            for row in user_rows:
                connection.execute(
                    text("UPDATE users SET access_token = :access_token WHERE id = :id"),
                    {"access_token": secrets.token_urlsafe(32), "id": row["id"]},
                )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_access_token ON users(access_token)")
            )
        else:
            user_rows = connection.execute(
                text("SELECT id FROM users WHERE access_token IS NULL OR access_token = ''")
            ).mappings()
            for row in user_rows:
                connection.execute(
                    text("UPDATE users SET access_token = :access_token WHERE id = :id"),
                    {"access_token": secrets.token_urlsafe(32), "id": row["id"]},
                )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_access_token ON users(access_token)")
            )
        if "telegram_external_id" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN telegram_external_id VARCHAR(120)"))
            connection.execute(
                text(
                    "UPDATE users SET telegram_external_id = external_id "
                    "WHERE source = 'telegram' AND external_id IS NOT NULL"
                )
            )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_telegram_external_id ON users(telegram_external_id)")
            )
        if "telegram_username" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN telegram_username VARCHAR(120)"))
            connection.execute(
                text(
                    "UPDATE users SET telegram_username = username "
                    "WHERE source = 'telegram' AND username IS NOT NULL"
                )
            )
        if "telegram_link_code" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN telegram_link_code VARCHAR(16)"))
        if "vk_external_id" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN vk_external_id VARCHAR(120)"))
            connection.execute(
                text(
                    "UPDATE users SET vk_external_id = external_id "
                    "WHERE source = 'vk' AND external_id IS NOT NULL"
                )
            )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_vk_external_id ON users(vk_external_id)")
            )
        if "vk_username" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN vk_username VARCHAR(120)"))
            connection.execute(
                text(
                    "UPDATE users SET vk_username = username "
                    "WHERE source = 'vk' AND username IS NOT NULL"
                )
            )
        if "vk_link_code" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN vk_link_code VARCHAR(16)"))
        if "ticket_mail_code" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN ticket_mail_code VARCHAR(24)"))
            user_rows = connection.execute(text("SELECT id FROM users")).mappings()
            used_codes: set[str] = set()
            for row in user_rows:
                code = make_ticket_mail_code()
                while code in used_codes:
                    code = make_ticket_mail_code()
                used_codes.add(code)
                connection.execute(
                    text("UPDATE users SET ticket_mail_code = :code WHERE id = :id"),
                    {"code": code, "id": row["id"]},
                )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_ticket_mail_code ON users(ticket_mail_code)")
            )
        else:
            user_rows = connection.execute(
                text("SELECT id FROM users WHERE ticket_mail_code IS NULL OR ticket_mail_code = ''")
            ).mappings()
            used_codes = set(
                connection.execute(
                    text("SELECT ticket_mail_code FROM users WHERE ticket_mail_code IS NOT NULL AND ticket_mail_code != ''")
                ).scalars()
            )
            for row in user_rows:
                code = make_ticket_mail_code()
                while code in used_codes:
                    code = make_ticket_mail_code()
                used_codes.add(code)
                connection.execute(
                    text("UPDATE users SET ticket_mail_code = :code WHERE id = :id"),
                    {"code": code, "id": row["id"]},
                )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_ticket_mail_code ON users(ticket_mail_code)")
            )
        if "bio" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN bio TEXT"))
        if "avatar_url" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(512)"))
        if "privacy_settings" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN privacy_settings JSON"))
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_telegram_external_id ON users(telegram_external_id)")
        )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_vk_external_id ON users(vk_external_id)")
        )
        duplicate_usernames = connection.execute(
            text(
                "SELECT username FROM users WHERE username IS NOT NULL AND username != '' "
                "GROUP BY username HAVING COUNT(*) > 1"
            )
        ).scalars()
        for username in duplicate_usernames:
            rows = connection.execute(
                text("SELECT id FROM users WHERE username = :username ORDER BY created_at, id"),
                {"username": username},
            ).mappings()
            for index, row in enumerate(rows):
                if index > 0:
                    connection.execute(text("UPDATE users SET username = NULL WHERE id = :id"), {"id": row["id"]})
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users(username)"))

        ticket_columns = {column["name"] for column in inspector.get_columns("tickets")}
        if "ticket_key" not in ticket_columns:
            connection.execute(text("ALTER TABLE tickets ADD COLUMN ticket_key VARCHAR(160)"))
            rows = connection.execute(
                text("SELECT id, fiscal_series, ticket_number FROM tickets ORDER BY created_at, id")
            ).mappings()
            seen_keys: set[str] = set()
            for row in rows:
                ticket_key = _ticket_key(row["fiscal_series"], row["ticket_number"])
                if ticket_key in seen_keys:
                    ticket_key = f"LEGACY_DUPLICATE:{row['id']}"
                seen_keys.add(ticket_key)
                connection.execute(
                    text("UPDATE tickets SET ticket_key = :ticket_key WHERE id = :id"),
                    {"ticket_key": ticket_key, "id": row["id"]},
                )
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_tickets_ticket_key ON tickets(ticket_key)"))
        if "personal_degree" not in ticket_columns:
            connection.execute(text("ALTER TABLE tickets ADD COLUMN personal_degree INTEGER"))
        if "personal_label" not in ticket_columns:
            connection.execute(text("ALTER TABLE tickets ADD COLUMN personal_label VARCHAR(80)"))
        if "uploaded_file_path" not in ticket_columns:
            connection.execute(text("ALTER TABLE tickets ADD COLUMN uploaded_file_path VARCHAR(512)"))
        if "uploaded_file_content_type" not in ticket_columns:
            connection.execute(text("ALTER TABLE tickets ADD COLUMN uploaded_file_content_type VARCHAR(120)"))


def _ticket_key(fiscal_series: str | None, ticket_number: str) -> str:
    series = fiscal_series.strip().upper() if fiscal_series else "NO_SERIES"
    number = ticket_number.strip().upper()
    return f"{series}:{number}"


def _refresh_happiness_translations() -> None:
    with SessionLocal() as db:
        rows = db.execute(
            select(Ticket.ticket_number, TicketHappiness).join(
                TicketHappiness,
                Ticket.id == TicketHappiness.ticket_id,
            )
        ).all()
        changed = False
        for ticket_number, happiness in rows:
            result = score_ticket_number(ticket_number[-4:])
            reasons = {
                "reasons": result.reasons,
                "matched_rules": result.matched_rules,
            }
            if (
                happiness.degree != result.degree
                or happiness.points != result.points
                or happiness.label != result.label
                or happiness.reasons != reasons
            ):
                happiness.degree = result.degree
                happiness.points = result.points
                happiness.label = result.label
                happiness.reasons = reasons
                changed = True
        if changed:
            db.commit()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

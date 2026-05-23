from datetime import UTC, datetime
import secrets
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


JsonType = JSON().with_variant(JSONB, "postgresql")


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_ticket_mail_code() -> str:
    return secrets.token_hex(5)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_users_source_external_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(32), default="web", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(120))
    username: Mapped[str | None] = mapped_column(String(120))
    telegram_external_id: Mapped[str | None] = mapped_column(String(120))
    telegram_username: Mapped[str | None] = mapped_column(String(120))
    telegram_link_code: Mapped[str | None] = mapped_column(String(16))
    vk_external_id: Mapped[str | None] = mapped_column(String(120))
    vk_username: Mapped[str | None] = mapped_column(String(120))
    vk_link_code: Mapped[str | None] = mapped_column(String(16))
    ticket_mail_code: Mapped[str] = mapped_column(String(24), default=make_ticket_mail_code, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    bio: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    privacy_settings: Mapped[dict | None] = mapped_column(JsonType)
    access_token: Mapped[str] = mapped_column(String(64), default=lambda: secrets.token_urlsafe(32), nullable=False)
    is_profile_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    personal_data_consent_given: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    tickets: Mapped[list["Ticket"]] = relationship(back_populates="user")


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("ticket_key", name="uq_tickets_ticket_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    ticket_key: Mapped[str] = mapped_column(String(160), nullable=False)
    ticket_number: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_series: Mapped[str | None] = mapped_column(String(64))
    source_format: Mapped[str] = mapped_column(String(80), default="unknown", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="parsed", nullable=False)
    personal_degree: Mapped[int | None] = mapped_column(Integer)
    personal_label: Mapped[str | None] = mapped_column(String(80))
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime)
    route_number: Mapped[str | None] = mapped_column(String(32))
    price_rub: Mapped[float | None] = mapped_column(Numeric(10, 2))
    uploaded_file_path: Mapped[str | None] = mapped_column(String(512))
    uploaded_file_content_type: Mapped[str | None] = mapped_column(String(120))
    raw_ocr_text: Mapped[str | None] = mapped_column(Text)
    parsed_payload: Mapped[dict | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="tickets")
    happiness: Mapped["TicketHappiness"] = relationship(back_populates="ticket")


class TicketHappiness(Base):
    __tablename__ = "ticket_happiness"

    ticket_id: Mapped[str] = mapped_column(String(36), ForeignKey("tickets.id"), primary_key=True)
    degree: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    reasons: Mapped[dict] = mapped_column(JsonType, nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="happiness")

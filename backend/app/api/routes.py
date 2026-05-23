from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.api.schemas import (
    BotDailyDigest,
    EkartaCheckRequest,
    EkartaCheckResponse,
    HappinessResponse,
    ParseTicketRequest,
    ParseTicketResponse,
    DailyStatsPoint,
    HourlyStatsPoint,
    TelegramDailyDigest,
    TelegramLinkCodeResponse,
    TelegramLinkRequest,
    TicketListResponse,
    TicketPersonalRatingRequest,
    TicketResponse,
    TicketSubmitRequest,
    TicketSubmitResponse,
    UserRegisterRequest,
    UserLoginRequest,
    UserPrivacyRequest,
    UserProfileUpdateRequest,
    UserProfileResponse,
    UserRegisterResponse,
    UserResponse,
    VkLinkRequest,
)
from app.core.settings import get_settings
from app.db.models import Ticket, TicketHappiness, User
from app.db.session import get_db
from app.fiscal.ekarta import EkartaFiscalClient, EkartaReceiptRequest
from app.happiness.rules import score_ticket_number
from app.notifications import notify_ticket_uploaded
from app.tickets.files import TicketFileError, extract_ticket_text
from app.tickets.parser import parse_ticket_text

router = APIRouter()

DEFAULT_PRIVACY: dict[str, bool] = {
    "show_about": True,
    "show_stats": True,
    "show_tickets": True,
    "show_photos": False,
    "show_telegram": True,
    "show_vk": True,
}
UPLOAD_DIR = Path("/data/ticket-files")
AVATAR_DIR = Path("/data/avatar-files")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/tickets/parse", response_model=ParseTicketResponse)
def parse_ticket(payload: ParseTicketRequest) -> ParseTicketResponse:
    parsed = parse_ticket_text(payload.text)
    happiness = score_ticket_number(parsed.ticket_number) if parsed.ticket_number else None
    return ParseTicketResponse(parsed=parsed, happiness=happiness)


@router.get("/happiness/{ticket_number}", response_model=HappinessResponse)
def get_happiness(ticket_number: str) -> HappinessResponse:
    return HappinessResponse(result=score_ticket_number(ticket_number))


@router.post("/users/register", response_model=UserRegisterResponse)
def register_user(payload: UserRegisterRequest, db: Session = Depends(get_db)) -> UserRegisterResponse:
    source = payload.source.strip().lower() or "web"
    external_id = payload.external_id.strip() if payload.external_id else None
    username = payload.username.strip().lstrip("@") if payload.username else None
    display_name = _clean_display_name(payload.display_name)
    if source == "web" and not payload.personal_data_consent:
        raise HTTPException(status_code=422, detail="Personal data consent is required")

    user = None
    if source == "telegram" and external_id:
        user = db.scalar(select(User).where(User.telegram_external_id == external_id))
    if source == "vk" and external_id:
        user = db.scalar(select(User).where(User.vk_external_id == external_id))
    if external_id:
        user = user or db.scalar(
            select(User).where(User.source == source, User.external_id == external_id)
        )
    _ensure_username_available(db, username, user.id if user else None)
    if source == "web":
        _ensure_display_name_available(db, display_name, user.id if user else None)

    created = user is None
    if user is None:
        user = User(
            source=source,
            external_id=external_id,
            username=username,
            telegram_external_id=external_id if source == "telegram" else None,
            telegram_username=username if source == "telegram" else None,
            vk_external_id=external_id if source == "vk" else None,
            vk_username=username if source == "vk" else None,
            display_name=display_name,
            bio=payload.bio.strip() if payload.bio else None,
            avatar_url=payload.avatar_url.strip() if payload.avatar_url else None,
            is_profile_public=payload.is_profile_public,
            personal_data_consent_given=payload.personal_data_consent,
            privacy_settings=DEFAULT_PRIVACY.copy(),
        )
        db.add(user)
    else:
        user.display_name = display_name
        user.username = username or user.username
        if payload.bio is not None:
            user.bio = payload.bio.strip() or None
        if payload.avatar_url is not None:
            user.avatar_url = payload.avatar_url.strip() or None
        user.privacy_settings = _privacy_settings(user)
        user.is_profile_public = payload.is_profile_public
        user.personal_data_consent_given = user.personal_data_consent_given or payload.personal_data_consent
        if source == "telegram":
            user.telegram_external_id = external_id or user.telegram_external_id
            user.telegram_username = username or user.telegram_username
        if source == "vk":
            user.vk_external_id = external_id or user.vk_external_id
            user.vk_username = username or user.vk_username

    db.commit()
    db.refresh(user)
    return UserRegisterResponse(
        user=_build_user_response(db, user),
        created=created,
        access_token=user.access_token,
    )


@router.post("/users/login", response_model=UserRegisterResponse)
def login_user(payload: UserLoginRequest, db: Session = Depends(get_db)) -> UserRegisterResponse:
    access_token = payload.access_token.strip()
    user = db.scalar(select(User).where(User.access_token == access_token))
    if user is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return UserRegisterResponse(
        user=_build_user_response(db, user),
        created=False,
        access_token=user.access_token,
    )


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: str, db: Session = Depends(get_db)) -> UserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_profile_public:
        raise HTTPException(status_code=403, detail="Profile is private")
    return _build_user_response(db, user, public_view=True)


@router.get("/users/{user_id}/profile", response_model=UserProfileResponse)
def get_user_profile(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_profile_public and not _has_user_token(request, user):
        raise HTTPException(status_code=403, detail="Profile is private")
    is_owner = _has_user_token(request, user)
    privacy = _privacy_settings(user)

    tickets = db.scalars(
        select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.purchased_at.desc().nullslast())
    ).all()
    visible_tickets = tickets if is_owner or privacy["show_tickets"] else []
    return UserProfileResponse(
        user=_build_user_response(db, user, public_view=not is_owner),
        daily_stats=_build_daily_stats(tickets) if is_owner or privacy["show_stats"] else [],
        hourly_stats=_build_hourly_stats(tickets) if is_owner or privacy["show_stats"] else [],
        tickets=[
            _build_ticket_response(ticket, include_image=is_owner or privacy["show_photos"])
            for ticket in visible_tickets
        ],
    )


@router.patch("/users/{user_id}/privacy", response_model=UserResponse)
def update_user_privacy(
    user_id: str,
    payload: UserPrivacyRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)
    if payload.is_profile_public is not None:
        user.is_profile_public = payload.is_profile_public
    privacy = _privacy_settings(user)
    for key in DEFAULT_PRIVACY:
        value = getattr(payload, key)
        if value is not None:
            privacy[key] = value
    user.privacy_settings = privacy
    db.commit()
    db.refresh(user)
    return _build_user_response(db, user)


@router.patch("/users/{user_id}/profile", response_model=UserResponse)
def update_user_profile(
    user_id: str,
    payload: UserProfileUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)

    if payload.username is not None:
        username = payload.username.strip().lstrip("@") or None
        _ensure_username_available(db, username, user.id)
        user.username = username
    if payload.display_name is not None:
        display_name = _clean_display_name(payload.display_name)
        _ensure_display_name_available(db, display_name, user.id)
        user.display_name = display_name
    if payload.bio is not None:
        user.bio = payload.bio.strip() or None
    if payload.avatar_url is not None:
        user.avatar_url = payload.avatar_url.strip() or None

    db.commit()
    db.refresh(user)
    return _build_user_response(db, user)


@router.post("/users/{user_id}/avatar", response_model=UserResponse)
async def upload_user_avatar(
    user_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Avatar must be an image")
    content = await file.read()
    extension = _image_extension(file.filename or "", content_type)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    for old_path in AVATAR_DIR.glob(f"{user.id}.*"):
        old_path.unlink(missing_ok=True)
    path = AVATAR_DIR / f"{user.id}{extension}"
    path.write_bytes(content)
    user.avatar_url = f"/api/users/{user.id}/avatar?v={secrets.token_urlsafe(6)}"
    db.commit()
    db.refresh(user)
    return _build_user_response(db, user)


@router.get("/users/{user_id}/avatar")
def get_user_avatar(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> FileResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    privacy = _privacy_settings(user)
    if not _has_user_token(request, user) and (not user.is_profile_public or not privacy["show_about"]):
        raise HTTPException(status_code=403, detail="Avatar is private")
    for path in AVATAR_DIR.glob(f"{user.id}.*"):
        return FileResponse(path, media_type=_media_type_for_path(path))
    raise HTTPException(status_code=404, detail="Avatar not found")


@router.post("/users/{user_id}/telegram-link-code", response_model=TelegramLinkCodeResponse)
def create_telegram_link_code(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> TelegramLinkCodeResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)
    user.telegram_link_code = _new_link_code(db)
    db.commit()
    return TelegramLinkCodeResponse(code=user.telegram_link_code)


@router.post("/users/{user_id}/vk-link-code", response_model=TelegramLinkCodeResponse)
def create_vk_link_code(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> TelegramLinkCodeResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)
    user.vk_link_code = _new_link_code(db)
    db.commit()
    return TelegramLinkCodeResponse(code=user.vk_link_code)


@router.post("/bot/telegram/link", response_model=UserRegisterResponse)
def link_telegram_account(
    payload: TelegramLinkRequest,
    db: Session = Depends(get_db),
) -> UserRegisterResponse:
    code = payload.code.strip()
    user = db.scalar(select(User).where(User.telegram_link_code == code))
    if user is None:
        raise HTTPException(status_code=404, detail="Link code not found")

    existing = db.scalar(select(User).where(User.telegram_external_id == payload.telegram_id))
    if existing is not None and existing.id != user.id:
        _reassign_provider_user(db, target=user, existing=existing, provider="telegram")

    username = payload.username.strip().lstrip("@") if payload.username else None
    user.telegram_external_id = payload.telegram_id
    user.telegram_username = username
    if payload.avatar_url and not user.avatar_url:
        user.avatar_url = payload.avatar_url.strip()
    user.telegram_link_code = None
    if user.source == "telegram":
        user.external_id = payload.telegram_id
    if username and user.username != username and _is_username_available(db, username, user.id):
        _ensure_username_available(db, username, user.id)
        user.username = user.username or username
    db.commit()
    db.refresh(user)
    return UserRegisterResponse(
        user=_build_user_response(db, user),
        created=False,
        access_token=user.access_token,
    )


@router.post("/bot/vk/link", response_model=UserRegisterResponse)
def link_vk_account(
    payload: VkLinkRequest,
    db: Session = Depends(get_db),
) -> UserRegisterResponse:
    code = payload.code.strip()
    user = db.scalar(select(User).where(User.vk_link_code == code))
    if user is None:
        raise HTTPException(status_code=404, detail="Link code not found")

    existing = db.scalar(select(User).where(User.vk_external_id == payload.vk_id))
    if existing is not None and existing.id != user.id:
        _reassign_provider_user(db, target=user, existing=existing, provider="vk")

    username = payload.username.strip().lstrip("@") if payload.username else None
    user.vk_external_id = payload.vk_id
    user.vk_username = username
    if payload.avatar_url and not user.avatar_url:
        user.avatar_url = payload.avatar_url.strip()
    user.vk_link_code = None
    if user.source == "vk":
        user.external_id = payload.vk_id
    if username and user.username != username and _is_username_available(db, username, user.id):
        _ensure_username_available(db, username, user.id)
        user.username = user.username or username
    db.commit()
    db.refresh(user)
    return UserRegisterResponse(
        user=_build_user_response(db, user),
        created=False,
        access_token=user.access_token,
    )


@router.delete("/users/{user_id}/telegram-link", response_model=UserResponse)
def unlink_telegram_account(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)
    user.telegram_external_id = None
    user.telegram_username = None
    if user.source == "telegram":
        user.external_id = None
    db.commit()
    db.refresh(user)
    return _build_user_response(db, user)


@router.delete("/users/{user_id}/vk-link", response_model=UserResponse)
def unlink_vk_account(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)
    user.vk_external_id = None
    user.vk_username = None
    if user.source == "vk":
        user.external_id = None
    db.commit()
    db.refresh(user)
    return _build_user_response(db, user)


@router.get("/leaderboard", response_model=list[UserResponse])
def get_leaderboard(db: Session = Depends(get_db)) -> list[UserResponse]:
    users = db.scalars(select(User).where(User.is_profile_public.is_(True))).all()
    rows = [_build_user_response(db, user, public_view=True) for user in users]
    return sorted(rows, key=lambda row: (row.points, row.verified_tickets_count), reverse=True)[:50]


@router.get("/bot/telegram/daily-digests", response_model=list[TelegramDailyDigest])
def get_telegram_daily_digests(
    request: Request,
    day: date | None = None,
    db: Session = Depends(get_db),
) -> list[TelegramDailyDigest]:
    _require_internal_token(request)
    target_day = day or date.today()
    users = db.scalars(
        select(User).where(
            User.telegram_external_id.is_not(None),
        )
    ).all()
    digests: list[TelegramDailyDigest] = []
    for user in users:
        chat_id = _parse_chat_id(user.telegram_external_id)
        if chat_id is None:
            continue
        tickets = [
            ticket
            for ticket in db.scalars(select(Ticket).where(Ticket.user_id == user.id)).all()
            if _ticket_day(ticket) == target_day
        ]
        stats = _build_daily_stats(tickets)
        digests.append(
            TelegramDailyDigest(
                user=_build_user_response(db, user),
                chat_id=chat_id,
                day=target_day.isoformat(),
                stats=stats[0] if stats else _empty_daily_stats(target_day),
                tickets=[_build_ticket_response(ticket) for ticket in tickets],
            )
        )
    return digests


@router.get("/bot/vk/daily-digests", response_model=list[BotDailyDigest])
def get_vk_daily_digests(
    request: Request,
    day: date | None = None,
    db: Session = Depends(get_db),
) -> list[BotDailyDigest]:
    _require_internal_token(request)
    target_day = day or date.today()
    users = db.scalars(
        select(User).where(
            User.vk_external_id.is_not(None),
        )
    ).all()
    digests: list[BotDailyDigest] = []
    for user in users:
        chat_id = _parse_chat_id(user.vk_external_id)
        if chat_id is None:
            continue
        tickets = [
            ticket
            for ticket in db.scalars(select(Ticket).where(Ticket.user_id == user.id)).all()
            if _ticket_day(ticket) == target_day
        ]
        stats = _build_daily_stats(tickets)
        digests.append(
            BotDailyDigest(
                user=_build_user_response(db, user),
                chat_id=chat_id,
                day=target_day.isoformat(),
                stats=stats[0] if stats else _empty_daily_stats(target_day),
                tickets=[_build_ticket_response(ticket) for ticket in tickets],
            )
        )
    return digests


@router.post("/users/{user_id}/tickets/submit", response_model=TicketSubmitResponse)
def submit_ticket(
    user_id: str,
    payload: TicketSubmitRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TicketSubmitResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)

    parsed = parse_ticket_text(payload.text)
    ticket = _create_ticket_from_text(db, user, payload.text, payload.status)
    background_tasks.add_task(notify_ticket_uploaded, user.id, ticket.id, _ticket_origin(request))
    return TicketSubmitResponse(ticket=_build_ticket_response(ticket, include_image=True), parsed=parsed)


@router.post("/users/{user_id}/tickets/upload", response_model=TicketSubmitResponse)
async def upload_ticket(
    user_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    personal_data_consent: bool = Form(False),
    db: Session = Depends(get_db),
) -> TicketSubmitResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)
    origin = _ticket_origin(request)
    if origin is None and _user_tickets_count(db, user.id) == 0 and not (
        personal_data_consent or user.personal_data_consent_given
    ):
        raise HTTPException(status_code=422, detail="Personal data consent is required for first ticket upload")
    if personal_data_consent and not user.personal_data_consent_given:
        user.personal_data_consent_given = True
        db.flush()
    content = await file.read()
    try:
        text = extract_ticket_text(content, filename=file.filename or "", content_type=file.content_type or "")
    except TicketFileError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    parsed = parse_ticket_text(text)
    ticket = _create_ticket_from_text(
        db,
        user,
        text,
        None,
        uploaded_content=content,
        uploaded_filename=file.filename or "",
        uploaded_content_type=file.content_type or "",
    )
    background_tasks.add_task(notify_ticket_uploaded, user.id, ticket.id, origin)
    return TicketSubmitResponse(ticket=_build_ticket_response(ticket, include_image=True), parsed=parsed)


@router.get("/users/{user_id}/tickets", response_model=TicketListResponse)
def list_user_tickets(
    user_id: str,
    request: Request,
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> TicketListResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    is_owner = _has_user_token(request, user)
    privacy = _privacy_settings(user)
    if not is_owner and (not user.is_profile_public or not privacy["show_tickets"]):
        raise HTTPException(status_code=403, detail="Tickets are private")

    total = db.scalar(select(func.count(Ticket.id)).where(Ticket.user_id == user.id)) or 0
    tickets = db.scalars(
        select(Ticket)
        .where(Ticket.user_id == user.id)
        .order_by(Ticket.purchased_at.desc().nullslast(), Ticket.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    next_offset = offset + limit if offset + limit < total else None
    prev_offset = max(0, offset - limit) if offset > 0 else None
    page_count = max(1, (total + limit - 1) // limit)
    page = min(page_count, offset // limit + 1)
    return TicketListResponse(
        items=[
            _build_ticket_response(ticket, include_image=is_owner or privacy["show_photos"])
            for ticket in tickets
        ],
        total=total,
        limit=limit,
        offset=offset,
        page=page,
        page_count=page_count,
        next_offset=next_offset,
        prev_offset=prev_offset,
    )


@router.patch("/tickets/{ticket_id}/personal-rating", response_model=TicketResponse)
def update_ticket_personal_rating(
    ticket_id: str,
    payload: TicketPersonalRatingRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TicketResponse:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    user = db.get(User, ticket.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)
    ticket.personal_degree = payload.degree
    ticket.personal_label = payload.label or f"личный класс {payload.degree}"
    db.commit()
    db.refresh(ticket)
    return _build_ticket_response(ticket, include_image=True)


@router.delete("/tickets/{ticket_id}", status_code=204)
def delete_unverified_ticket(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    user = db.get(User, ticket.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_token(request, user)
    if ticket.status == "verified":
        raise HTTPException(status_code=409, detail="Verified tickets cannot be deleted")

    uploaded_file_path = Path(ticket.uploaded_file_path) if ticket.uploaded_file_path else None
    db.execute(delete(TicketHappiness).where(TicketHappiness.ticket_id == ticket.id))
    db.delete(ticket)
    db.commit()
    if uploaded_file_path and uploaded_file_path.exists():
        uploaded_file_path.unlink(missing_ok=True)
    return Response(status_code=204)


@router.get("/tickets/{ticket_id}/image")
def get_ticket_image(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> FileResponse:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or not ticket.uploaded_file_path:
        raise HTTPException(status_code=404, detail="Ticket image not found")
    user = db.get(User, ticket.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    privacy = _privacy_settings(user)
    if not _has_user_token(request, user) and (not user.is_profile_public or not privacy["show_photos"]):
        raise HTTPException(status_code=403, detail="Ticket image is private")
    path = Path(ticket.uploaded_file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Ticket image not found")
    return FileResponse(path, media_type=ticket.uploaded_file_content_type or "application/octet-stream")


@router.post("/fiscal/ekarta/check", response_model=EkartaCheckResponse)
async def check_ekarta(payload: EkartaCheckRequest) -> EkartaCheckResponse:
    settings = get_settings()
    client = EkartaFiscalClient(base_url=settings.ekarta_fiscal_base_url)
    result = await client.check(
        EkartaReceiptRequest(series=payload.series, number=payload.number, is_qr=payload.is_qr)
    )
    return EkartaCheckResponse(result=result)


def _build_user_response(db: Session, user: User, public_view: bool = False) -> UserResponse:
    privacy = _privacy_settings(user)
    expose_telegram = not public_view or privacy["show_telegram"]
    expose_vk = not public_view or privacy["show_vk"]
    tickets_count = _user_tickets_count(db, user.id)
    verified_tickets_count = (
        db.scalar(
            select(func.count(Ticket.id)).where(Ticket.user_id == user.id, Ticket.status == "verified")
        )
        or 0
    )
    points = (
        db.scalar(
            select(func.coalesce(func.sum(TicketHappiness.points), 0))
            .join(Ticket, Ticket.id == TicketHappiness.ticket_id)
            .where(Ticket.user_id == user.id, Ticket.status == "verified")
        )
        or 0
    )
    return UserResponse(
        id=user.id,
        display_name=user.display_name,
        source=user.source,
        external_id=user.external_id,
        username=user.username,
        telegram_username=user.telegram_username if expose_telegram else None,
        telegram_linked=user.telegram_external_id is not None and expose_telegram,
        vk_username=user.vk_username if expose_vk else None,
        vk_linked=user.vk_external_id is not None and expose_vk,
        bio=user.bio if not public_view or privacy["show_about"] else None,
        avatar_url=user.avatar_url if not public_view or privacy["show_about"] else None,
        privacy_settings=privacy if not public_view else {},
        is_profile_public=user.is_profile_public,
        personal_data_consent_given=user.personal_data_consent_given if not public_view else False,
        tickets_count=tickets_count,
        verified_tickets_count=verified_tickets_count,
        points=points,
        ticket_mail_address=_ticket_mail_address(user) if not public_view else None,
    )


def _user_tickets_count(db: Session, user_id: str) -> int:
    return db.scalar(select(func.count(Ticket.id)).where(Ticket.user_id == user_id)) or 0


def _default_ticket_status(source_format: str) -> str:
    if source_format in {"ekarta_ek_qr_pdf_v1", "nspk_sbp_email_v1"}:
        return "verified"
    return "pending_check"


def _ticket_mail_address(user: User) -> str | None:
    settings = get_settings()
    template = settings.ticket_mail_public_address_template.strip()
    if not settings.ticket_mail_enabled:
        return None
    if not template or not user.ticket_mail_code:
        return None
    return template.replace("{code}", user.ticket_mail_code)


def _privacy_settings(user: User) -> dict[str, bool]:
    settings = DEFAULT_PRIVACY.copy()
    if isinstance(user.privacy_settings, dict):
        for key, value in user.privacy_settings.items():
            if key in settings:
                settings[key] = bool(value)
    return settings


def _ensure_username_available(db: Session, username: str | None, current_user_id: str | None = None) -> None:
    if not username:
        return
    existing = db.scalar(select(User).where(User.username == username))
    if existing is not None and existing.id != current_user_id:
        raise HTTPException(status_code=409, detail="Username is already taken")


def _clean_display_name(display_name: str) -> str:
    cleaned = " ".join(display_name.strip().split())
    if not cleaned:
        raise HTTPException(status_code=422, detail="Display name is required")
    return cleaned


def _ensure_display_name_available(
    db: Session,
    display_name: str,
    current_user_id: str | None = None,
) -> None:
    existing = db.scalar(select(User).where(func.lower(User.display_name) == display_name.lower()))
    if existing is not None and existing.id != current_user_id:
        raise HTTPException(status_code=409, detail="Display name is already taken")


def _is_username_available(db: Session, username: str | None, current_user_id: str | None = None) -> bool:
    if not username:
        return False
    existing = db.scalar(select(User).where(User.username == username))
    return existing is None or existing.id == current_user_id


def _reassign_provider_user(db: Session, target: User, existing: User, provider: str) -> None:
    if existing.id == target.id:
        return
    if existing.source != provider:
        provider_username = (
            existing.telegram_username if provider == "telegram" else existing.vk_username
        )
        _clear_provider_link(existing, provider)
        if provider_username and existing.username == provider_username:
            existing.username = None
        db.flush()
        return

    db.execute(update(Ticket).where(Ticket.user_id == existing.id).values(user_id=target.id))
    if not target.avatar_url and existing.avatar_url:
        target.avatar_url = existing.avatar_url
    if not target.bio and existing.bio:
        target.bio = existing.bio
    _clear_provider_link(existing, provider)
    existing.username = None
    existing.external_id = None
    db.flush()
    db.delete(existing)


def _clear_provider_link(user: User, provider: str) -> None:
    if provider == "telegram":
        user.telegram_external_id = None
        user.telegram_username = None
        if user.source == "telegram":
            user.external_id = None
    elif provider == "vk":
        user.vk_external_id = None
        user.vk_username = None
        if user.source == "vk":
            user.external_id = None
    else:
        raise HTTPException(status_code=500, detail="Unknown provider")


def _create_ticket_from_text(
    db: Session,
    user: User,
    text: str,
    status_override: str | None,
    uploaded_content: bytes | None = None,
    uploaded_filename: str = "",
    uploaded_content_type: str = "",
) -> Ticket:
    parsed = parse_ticket_text(text)
    if not parsed.ticket_number:
        raise HTTPException(status_code=422, detail="Ticket number was not recognized")

    ticket_key = _ticket_key(parsed.fiscal_series, parsed.ticket_number)
    duplicate = db.scalar(select(Ticket).where(Ticket.ticket_key == ticket_key))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Ticket was already submitted")

    happiness = score_ticket_number(parsed.ticket_number[-4:])
    status = status_override or _default_ticket_status(parsed.source_format)
    ticket = Ticket(
        user_id=user.id,
        ticket_key=ticket_key,
        ticket_number=parsed.ticket_number,
        fiscal_series=parsed.fiscal_series,
        source_format=parsed.source_format,
        status=status,
        purchased_at=parsed.purchased_at,
        route_number=parsed.route_number,
        price_rub=Decimal(parsed.price_rub) if parsed.price_rub is not None else None,
        raw_ocr_text=text,
        parsed_payload=parsed.model_dump(mode="json"),
    )
    db.add(ticket)
    db.flush()
    if uploaded_content and uploaded_content_type.startswith("image/"):
        ticket.uploaded_file_path = _save_ticket_image(ticket.id, uploaded_content, uploaded_filename, uploaded_content_type)
        ticket.uploaded_file_content_type = uploaded_content_type
    db.add(
        TicketHappiness(
            ticket_id=ticket.id,
            degree=happiness.degree,
            points=happiness.points,
            label=happiness.label,
            reasons={
                "reasons": happiness.reasons,
                "matched_rules": happiness.matched_rules,
            },
        )
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ticket was already submitted") from error
    db.refresh(ticket)
    return ticket


def _save_ticket_image(ticket_id: str, content: bytes, filename: str, content_type: str) -> str:
    extension = _image_extension(filename, content_type)
    digest = hashlib.sha256(content).hexdigest()[:12]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{ticket_id}-{digest}{extension}"
    path.write_bytes(content)
    return str(path)


def _image_extension(filename: str, content_type: str) -> str:
    lowered_name = filename.lower()
    for extension in (".jpg", ".jpeg", ".png", ".webp"):
        if lowered_name.endswith(extension):
            return ".jpg" if extension == ".jpeg" else extension
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    return ".jpg"


def _media_type_for_path(path: Path) -> str:
    if path.suffix == ".png":
        return "image/png"
    if path.suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def _ticket_key(fiscal_series: str | None, ticket_number: str) -> str:
    series = fiscal_series.strip().upper() if fiscal_series else "NO_SERIES"
    number = ticket_number.strip().upper()
    return f"{series}:{number}"


def _new_link_code(db: Session) -> str:
    for _ in range(20):
        code = f"{secrets.randbelow(1_000_000):06d}"
        telegram_match = db.scalar(select(User).where(User.telegram_link_code == code))
        vk_match = db.scalar(select(User).where(User.vk_link_code == code))
        if telegram_match is None and vk_match is None:
            return code
    raise HTTPException(status_code=500, detail="Could not allocate link code")


def _has_user_token(request: Request, user: User) -> bool:
    token = request.headers.get("x-user-token", "") or request.query_params.get("token", "")
    return bool(token) and secrets.compare_digest(token, user.access_token)


def _require_user_token(request: Request, user: User) -> None:
    if not _has_user_token(request, user):
        raise HTTPException(status_code=403, detail="Invalid user token")


def _require_internal_token(request: Request) -> None:
    expected_token = get_settings().internal_api_token
    if not expected_token:
        return
    token = request.headers.get("x-internal-token", "")
    if not token or not secrets.compare_digest(token, expected_token):
        raise HTTPException(status_code=403, detail="Invalid internal token")


def _parse_chat_id(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _ticket_origin(request: Request) -> str | None:
    origin = request.headers.get("x-ticket-origin", "").strip().lower()
    return origin if origin in {"telegram", "vk"} else None


def _ticket_day(ticket: Ticket) -> date:
    value = ticket.purchased_at or ticket.created_at
    return value.date()


def _ticket_hour(ticket: Ticket) -> int:
    value = ticket.purchased_at or ticket.created_at
    return value.hour


def _personal_points(ticket: Ticket) -> int:
    if ticket.personal_degree is None:
        return ticket.happiness.points if ticket.happiness else 0
    return _points_for_degree(ticket.personal_degree)


def _official_degree(ticket: Ticket) -> int:
    return ticket.happiness.degree if ticket.happiness else 0


def _personal_degree(ticket: Ticket) -> int:
    return ticket.personal_degree if ticket.personal_degree is not None else _official_degree(ticket)


def _official_happiness_value(ticket: Ticket) -> int:
    return max(0, 5 - _official_degree(ticket))


def _personal_happiness_value(ticket: Ticket) -> int:
    return max(0, 5 - _personal_degree(ticket))


def _build_ticket_response(ticket: Ticket, include_image: bool = False) -> TicketResponse:
    happiness = ticket.happiness
    official_degree = happiness.degree if happiness else 0
    official_points = happiness.points if happiness else 0
    official_label = happiness.label if happiness else "unknown"
    return TicketResponse(
        id=ticket.id,
        user_id=ticket.user_id,
        ticket_number=ticket.ticket_number,
        fiscal_series=ticket.fiscal_series,
        source_format=ticket.source_format,
        status=ticket.status,
        purchased_at=ticket.purchased_at.isoformat() if ticket.purchased_at else None,
        day=_ticket_day(ticket).isoformat(),
        route_number=ticket.route_number,
        official_degree=official_degree,
        official_points=official_points,
        official_label=official_label,
        image_url=f"/api/tickets/{ticket.id}/image" if include_image and ticket.uploaded_file_path else None,
        personal_degree=ticket.personal_degree,
        personal_points=_personal_points(ticket),
        personal_label=ticket.personal_label,
    )


def _points_for_degree(degree: int) -> int:
    return {0: 1000, 1: 700, 2: 500, 3: 350, 4: 150, 5: 1}.get(degree, 1)


def _build_daily_stats(tickets: list[Ticket]) -> list[DailyStatsPoint]:
    grouped: dict[str, list[Ticket]] = {}
    for ticket in tickets:
        grouped.setdefault(_ticket_day(ticket).isoformat(), []).append(ticket)

    points: list[DailyStatsPoint] = []
    for day, day_tickets in sorted(grouped.items()):
        best = min(
            day_tickets,
            key=_official_degree,
            default=None,
        )
        ticket_count = len(day_tickets)
        official_happiness_sum = sum(_official_happiness_value(ticket) for ticket in day_tickets)
        personal_happiness_sum = sum(_personal_happiness_value(ticket) for ticket in day_tickets)
        points.append(
            DailyStatsPoint(
                day=day,
                tickets_count=ticket_count,
                verified_tickets_count=sum(1 for ticket in day_tickets if ticket.status == "verified"),
                official_happiness=round(official_happiness_sum / ticket_count, 2) if ticket_count else 0,
                personal_happiness=round(personal_happiness_sum / ticket_count, 2) if ticket_count else 0,
                official_points=sum(ticket.happiness.points for ticket in day_tickets if ticket.happiness),
                personal_points=sum(_personal_points(ticket) for ticket in day_tickets),
                best_ticket=best.ticket_number[-4:] if best else None,
                best_degree=_official_degree(best) if best else None,
            )
        )
    return points


def _build_hourly_stats(tickets: list[Ticket]) -> list[HourlyStatsPoint]:
    grouped: dict[tuple[str, int], list[Ticket]] = {}
    for ticket in tickets:
        grouped.setdefault((_ticket_day(ticket).isoformat(), _ticket_hour(ticket)), []).append(ticket)

    points: list[HourlyStatsPoint] = []
    for (day, hour), hour_tickets in sorted(grouped.items()):
        best = min(hour_tickets, key=_official_degree, default=None)
        ticket_count = len(hour_tickets)
        official_happiness_sum = sum(_official_happiness_value(ticket) for ticket in hour_tickets)
        personal_happiness_sum = sum(_personal_happiness_value(ticket) for ticket in hour_tickets)
        points.append(
            HourlyStatsPoint(
                day=day,
                hour=hour,
                tickets_count=ticket_count,
                official_happiness=round(official_happiness_sum / ticket_count, 2) if ticket_count else 0,
                personal_happiness=round(personal_happiness_sum / ticket_count, 2) if ticket_count else 0,
                official_points=sum(ticket.happiness.points for ticket in hour_tickets if ticket.happiness),
                personal_points=sum(_personal_points(ticket) for ticket in hour_tickets),
                best_ticket=best.ticket_number[-4:] if best else None,
                best_degree=_official_degree(best) if best else None,
            )
        )
    return points


def _empty_daily_stats(day: date) -> DailyStatsPoint:
    return DailyStatsPoint(
        day=day.isoformat(),
        tickets_count=0,
        verified_tickets_count=0,
        official_happiness=0,
        personal_happiness=0,
        official_points=0,
        personal_points=0,
        best_ticket=None,
        best_degree=None,
    )

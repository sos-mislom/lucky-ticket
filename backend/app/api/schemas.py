from pydantic import BaseModel, Field

from app.fiscal.ekarta import EkartaReceiptResult
from app.happiness.rules import HappinessResult
from app.tickets.models import TicketParseResult


class ParseTicketRequest(BaseModel):
    text: str = Field(..., description="OCR text extracted from a ticket image or PDF.")


class ParseTicketResponse(BaseModel):
    parsed: TicketParseResult
    happiness: HappinessResult | None


class HappinessResponse(BaseModel):
    result: HappinessResult


class UserRegisterRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120, examples=["Алексей"])
    source: str = Field("web", max_length=32, examples=["telegram"])
    external_id: str | None = Field(None, max_length=120, examples=["123456789"])
    username: str | None = Field(None, max_length=120, examples=["alex"])
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = Field(None, max_length=512)
    is_profile_public: bool = True
    personal_data_consent: bool = False


class UserResponse(BaseModel):
    id: str
    display_name: str
    source: str
    external_id: str | None = None
    username: str | None = None
    telegram_username: str | None = None
    telegram_linked: bool = False
    vk_username: str | None = None
    vk_linked: bool = False
    bio: str | None = None
    avatar_url: str | None = None
    privacy_settings: dict[str, bool] = {}
    is_profile_public: bool = True
    personal_data_consent_given: bool = False
    tickets_count: int = 0
    verified_tickets_count: int = 0
    points: int = 0
    ticket_mail_address: str | None = None


class UserRegisterResponse(BaseModel):
    user: UserResponse
    created: bool
    access_token: str


class UserLoginRequest(BaseModel):
    access_token: str = Field(..., min_length=16, max_length=120)


class UserPrivacyRequest(BaseModel):
    is_profile_public: bool | None = None
    show_about: bool | None = None
    show_stats: bool | None = None
    show_tickets: bool | None = None
    show_photos: bool | None = None
    show_telegram: bool | None = None
    show_vk: bool | None = None


class UserProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=120)
    username: str | None = Field(None, max_length=120)
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = Field(None, max_length=512)


class TelegramLinkCodeResponse(BaseModel):
    code: str


class TelegramLinkRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=16)
    telegram_id: str = Field(..., min_length=1, max_length=120)
    username: str | None = Field(None, max_length=120)
    display_name: str = Field(..., min_length=1, max_length=120)
    avatar_url: str | None = Field(None, max_length=512)


class VkLinkRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=16)
    vk_id: str = Field(..., min_length=1, max_length=120)
    username: str | None = Field(None, max_length=120)
    display_name: str = Field(..., min_length=1, max_length=120)
    avatar_url: str | None = Field(None, max_length=512)


class TicketSubmitRequest(BaseModel):
    text: str = Field(..., min_length=1)
    status: str | None = Field(None, examples=["verified", "pending_check"])


class TicketResponse(BaseModel):
    id: str
    user_id: str
    ticket_number: str
    fiscal_series: str | None = None
    source_format: str
    status: str
    purchased_at: str | None = None
    day: str
    route_number: str | None = None
    official_degree: int
    official_points: int
    official_label: str
    image_url: str | None = None
    personal_degree: int | None = None
    personal_points: int | None = None
    personal_label: str | None = None


class TicketSubmitResponse(BaseModel):
    ticket: TicketResponse
    parsed: TicketParseResult


class TicketListResponse(BaseModel):
    items: list[TicketResponse]
    total: int
    limit: int
    offset: int
    page: int
    page_count: int
    next_offset: int | None = None
    prev_offset: int | None = None


class TicketPersonalRatingRequest(BaseModel):
    degree: int = Field(..., ge=0, le=5)
    label: str | None = Field(None, max_length=80)


class DailyStatsPoint(BaseModel):
    day: str
    tickets_count: int
    verified_tickets_count: int
    official_happiness: float
    personal_happiness: float
    official_points: int
    personal_points: int
    best_ticket: str | None = None
    best_degree: int | None = None


class HourlyStatsPoint(BaseModel):
    day: str
    hour: int
    tickets_count: int
    official_happiness: float
    personal_happiness: float
    official_points: int
    personal_points: int
    best_ticket: str | None = None
    best_degree: int | None = None


class UserProfileResponse(BaseModel):
    user: UserResponse
    daily_stats: list[DailyStatsPoint]
    hourly_stats: list[HourlyStatsPoint]
    tickets: list[TicketResponse]


class TelegramDailyDigest(BaseModel):
    user: UserResponse
    chat_id: int
    day: str
    stats: DailyStatsPoint
    tickets: list[TicketResponse]


class BotDailyDigest(BaseModel):
    user: UserResponse
    chat_id: int
    day: str
    stats: DailyStatsPoint
    tickets: list[TicketResponse]


class EkartaCheckRequest(BaseModel):
    series: str = Field(..., examples=["260428-00000001-052", "26042800000001052"])
    number: str = Field(..., examples=["0369"])
    is_qr: bool = False


class EkartaCheckResponse(BaseModel):
    result: EkartaReceiptResult

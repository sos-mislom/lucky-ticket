import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BadgeCheck,
  Camera,
  Check,
  ChartNoAxesCombined,
  Copy,
  Eye,
  EyeOff,
  ExternalLink,
  FileText,
  Link2,
  LogIn,
  LogOut,
  Loader2,
  Search,
  Trash2,
  Trophy,
  UploadCloud,
  UserRound,
} from "lucide-react";
import "./styles.css";

type User = {
  id: string;
  display_name: string;
  source: string;
  username: string | null;
  telegram_username: string | null;
  telegram_linked: boolean;
  vk_username: string | null;
  vk_linked: boolean;
  bio: string | null;
  avatar_url: string | null;
  privacy_settings: Record<string, boolean>;
  is_profile_public: boolean;
  personal_data_consent_given: boolean;
  tickets_count: number;
  verified_tickets_count: number;
  points: number;
  ticket_mail_address: string | null;
};

type Ticket = {
  id: string;
  ticket_number: string;
  fiscal_series: string | null;
  status: string;
  purchased_at: string | null;
  day: string;
  route_number: string | null;
  official_degree: number;
  official_points: number;
  official_label: string;
  image_url: string | null;
  personal_degree: number | null;
  personal_points: number | null;
  personal_label: string | null;
};

type DailyStatsPoint = {
  day: string;
  tickets_count: number;
  verified_tickets_count: number;
  official_happiness: number;
  personal_happiness: number;
  official_points: number;
  personal_points: number;
  best_ticket: string | null;
  best_degree: number | null;
};

type HourlyStatsPoint = {
  day: string;
  hour: number;
  tickets_count: number;
  official_happiness: number;
  personal_happiness: number;
  official_points: number;
  personal_points: number;
  best_ticket: string | null;
  best_degree: number | null;
};

type Profile = {
  user: User;
  daily_stats: DailyStatsPoint[];
  hourly_stats: HourlyStatsPoint[];
  tickets: Ticket[];
};

type UserSession = {
  user: User;
  access_token: string;
};

type ProfileFormState = {
  display_name: string;
  username: string;
  bio: string;
};

type HappinessResult = {
  ticket_number: string;
  degree: number;
  points: number;
  label: string;
  reasons: string[];
};

type AuthMode = "login" | "register";
type AppView = "landing" | "top" | "auth" | "profile" | "tickets" | "account";

const statusLabels: Record<string, string> = {
  ready: "Готово",
  profile_loading: "Загружаю профиль",
  profile_loaded: "Профиль открыт",
  profile_private: "Профиль приватный",
  profile_error: "Не удалось открыть профиль",
  name_required: "Введите имя",
  token_required: "Введите код входа",
  login_error: "Профиль не найден",
  logged_in: "Вход выполнен",
  logged_out: "Вы вышли",
  register_error: "Ошибка регистрации",
  registered: "Профиль создан",
  updated: "Профиль обновлен",
  register_first: "Сначала зарегистрируйтесь",
  ticket_file_required: "Выберите PDF или фото",
  ticket_duplicate: "Билет уже засчитан",
  ticket_parse_error: "Билет не распознан",
  ticket_uploading: "Распознаю билет",
  ticket_saved: "Билет засчитан",
  ticket_deleted: "Билет удален",
  ticket_delete_error: "Не удалось удалить билет",
  check_digits_required: "Введите 4 цифры",
  check_error: "Не удалось проверить",
  checked: "Проверено",
  profile_public: "Профиль публичный",
  privacy_private: "Профиль скрыт",
  privacy_updated: "Приватность обновлена",
  profile_saved: "Профиль сохранен",
  username_taken: "Юзернейм уже занят",
  avatar_saved: "Аватарка обновлена",
  avatar_error: "Не удалось обновить аватарку",
  telegram_unlinked: "Telegram отвязан",
  telegram_code_ready: "Код для Telegram готов",
  telegram_code_error: "Не удалось создать код",
  vk_unlinked: "VK отвязан",
  vk_code_ready: "Код для VK готов",
  vk_code_error: "Не удалось создать код для VK",
  copied: "Скопировано",
};

const ticketStatusLabels: Record<string, string> = {
  verified: "проверен",
  pending_check: "ждет проверки",
  parsed: "распознан",
  not_found: "не найден у фискализатора",
  check_error: "ошибка проверки",
};

const LEGAL_LINKS = {
  personalDataPolicy: "/legal/personal-data-policy.html",
  personalDataConsent: "/legal/personal-data-consent.html",
};

function App() {
  const [activeView, setActiveView] = useState<AppView>("landing");
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [displayName, setDisplayName] = useState("");
  const [loginToken, setLoginToken] = useState("");
  const [registeredUser, setRegisteredUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [tokenVisible, setTokenVisible] = useState(false);
  const [copiedValue, setCopiedValue] = useState<string | null>(null);
  const [leaderboard, setLeaderboard] = useState<User[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [ticketFile, setTicketFile] = useState<File | null>(null);
  const [ticketPreviewUrl, setTicketPreviewUrl] = useState<string | null>(null);
  const [ticketUploading, setTicketUploading] = useState(false);
  const [registerConsent, setRegisterConsent] = useState(false);
  const [ticketConsent, setTicketConsent] = useState(false);
  const [cookiesAccepted, setCookiesAccepted] = useState(
    () => window.localStorage.getItem("lucky-ticket-cookies") === "accepted",
  );
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [checkDigits, setCheckDigits] = useState("");
  const [checkResult, setCheckResult] = useState<HappinessResult | null>(null);
  const [telegramCode, setTelegramCode] = useState<string | null>(null);
  const [vkCode, setVkCode] = useState<string | null>(null);
  const [profileForm, setProfileForm] = useState<ProfileFormState>({
    display_name: "",
    username: "",
    bio: "",
  });
  const [status, setStatus] = useState("ready");

  useEffect(() => {
    void bootstrapSession();
  }, []);

  useEffect(() => {
    if (registeredUser && accessToken) {
      window.localStorage.setItem(
        "lucky-ticket-session",
        JSON.stringify({ user: registeredUser, access_token: accessToken }),
      );
    }
  }, [registeredUser, accessToken]);

  useEffect(() => {
    if (!registeredUser) {
      return;
    }
    setProfileForm({
      display_name: registeredUser.display_name,
      username: registeredUser.username ?? "",
      bio: registeredUser.bio ?? "",
    });
  }, [registeredUser]);

  useEffect(() => {
    if (!ticketFile || !isPreviewableImage(ticketFile)) {
      setTicketPreviewUrl(null);
      return;
    }

    const previewUrl = URL.createObjectURL(ticketFile);
    setTicketPreviewUrl(previewUrl);
    return () => URL.revokeObjectURL(previewUrl);
  }, [ticketFile]);

  async function bootstrapSession() {
    const searchParams = new URLSearchParams(window.location.search);
    const urlToken = searchParams.get("token") || searchParams.get("access_token") || searchParams.get("tg_token");
    const requestedView = parseAppView(searchParams.get("view"));
    if (urlToken) {
      await loginWithToken(urlToken, requestedView ?? "tickets");
      searchParams.delete("token");
      searchParams.delete("access_token");
      searchParams.delete("tg_token");
      searchParams.delete("view");
      const nextSearch = searchParams.toString();
      const nextUrl = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}${window.location.hash}`;
      window.history.replaceState({}, "", nextUrl);
      return;
    }

    const savedSession = window.localStorage.getItem("lucky-ticket-session");
    if (savedSession) {
      try {
        const session = JSON.parse(savedSession) as UserSession;
        setRegisteredUser(session.user);
        setAccessToken(session.access_token);
      } catch {
        window.localStorage.removeItem("lucky-ticket-session");
      }
    }
    await loadLeaderboard();
  }

  async function loadLeaderboard() {
    const response = await fetch("/api/leaderboard");
    if (response.ok) {
      setLeaderboard((await response.json()) as User[]);
    }
  }

  async function loginWithToken(token: string, nextView: AppView = "profile") {
    const response = await fetch("/api/users/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: token }),
    });
    if (!response.ok) {
      setStatus("login_error");
      await loadLeaderboard();
      return;
    }
    const payload = (await response.json()) as UserSession;
    setRegisteredUser(payload.user);
    setAccessToken(payload.access_token);
    setLoginToken("");
    setStatus("logged_in");
    await loadProfile(payload.user.id);
    if (nextView !== "profile") {
      setActiveView(nextView);
    }
    await loadLeaderboard();
  }

  async function copyText(value: string) {
    if (!value) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setCopiedValue(value);
    setStatus("copied");
    window.setTimeout(() => setCopiedValue((current) => (current === value ? null : current)), 1800);
  }

  async function openTop() {
    setProfile(null);
    setActiveView("top");
    setStatus("ready");
    await loadLeaderboard();
  }

  async function loadProfile(userId: string, nextView: AppView = "profile") {
    setStatus("profile_loading");
    const response = await fetch(`/api/users/${userId}/profile`, {
      headers: authHeaders(userId),
    });
    if (!response.ok) {
      setStatus(response.status === 403 ? "profile_private" : "profile_error");
      return;
    }
    const loadedProfile = (await response.json()) as Profile;
    setProfile(loadedProfile);
    if (registeredUser?.id === loadedProfile.user.id) {
      setRegisteredUser(loadedProfile.user);
    }
    setActiveView(nextView);
    setStatus("profile_loaded");
  }

  async function registerUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = displayName.trim();
    if (!name) {
      setStatus("name_required");
      return;
    }
    const response = await fetch("/api/users/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: name,
        source: "web",
        is_profile_public: true,
        personal_data_consent: registerConsent,
      }),
    });
    if (!response.ok) {
      setStatus("register_error");
      return;
    }
    const payload = (await response.json()) as UserSession & { created: boolean };
    setRegisteredUser(payload.user);
    setAccessToken(payload.access_token);
    setLoginToken("");
    setRegisterConsent(false);
    setStatus(payload.created ? "registered" : "updated");
    await loadProfile(payload.user.id);
    await loadLeaderboard();
  }

  async function loginUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = loginToken.trim();
    if (!token) {
      setStatus("token_required");
      return;
    }
    await loginWithToken(token);
  }

  function logoutUser() {
    window.localStorage.removeItem("lucky-ticket-session");
    setRegisteredUser(null);
    setAccessToken(null);
    setTokenVisible(false);
    setCopiedValue(null);
    setProfile(null);
    setTelegramCode(null);
    setVkCode(null);
    setAuthMode("login");
    setActiveView("landing");
    setStatus("logged_out");
  }

  async function checkTicketDigits(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (checkDigits.length !== 4) {
      setStatus("check_digits_required");
      return;
    }
    const response = await fetch(`/api/happiness/${checkDigits}`);
    if (!response.ok) {
      setStatus("check_error");
      return;
    }
    const payload = (await response.json()) as { result: HappinessResult };
    setCheckResult(payload.result);
    setStatus("checked");
  }

  async function uploadTicket(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ticketUploading) {
      return;
    }
    if (!registeredUser) {
      setStatus("register_first");
      return;
    }
    if (!ticketFile) {
      setStatus("ticket_file_required");
      return;
    }

    const formData = new FormData();
    formData.append("file", ticketFile);
    formData.append("personal_data_consent", String(ticketConsent || registeredUser.personal_data_consent_given));
    setStatus("ticket_uploading");
    setTicketUploading(true);
    try {
      const response = await fetch(`/api/users/${registeredUser.id}/tickets/upload`, {
        method: "POST",
        headers: authHeaders(registeredUser.id),
        body: formData,
      });
      if (!response.ok) {
        setStatus(response.status === 409 ? "ticket_duplicate" : "ticket_parse_error");
        return;
      }
      setTicketFile(null);
      setTicketConsent(false);
      setFileInputKey((value) => value + 1);
      setStatus("ticket_saved");
      await loadProfile(registeredUser.id, "tickets");
      await loadLeaderboard();
    } catch {
      setStatus("ticket_parse_error");
    } finally {
      setTicketUploading(false);
    }
  }

  async function updatePrivacy(payload: Record<string, boolean>) {
    if (!registeredUser) {
      return;
    }
    const response = await fetch(`/api/users/${registeredUser.id}/privacy`, {
      method: "PATCH",
      headers: authHeaders(registeredUser.id, { "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      const user = (await response.json()) as User;
      setRegisteredUser(user);
      setStatus(payload.is_profile_public === false ? "privacy_private" : "privacy_updated");
      await loadProfile(user.id, activeView);
      await loadLeaderboard();
    }
  }

  async function setPrivacy(isPublic: boolean) {
    await updatePrivacy({ is_profile_public: isPublic });
  }

  async function saveProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!registeredUser) {
      return;
    }
    const response = await fetch(`/api/users/${registeredUser.id}/profile`, {
      method: "PATCH",
      headers: authHeaders(registeredUser.id, { "Content-Type": "application/json" }),
      body: JSON.stringify({
        display_name: profileForm.display_name,
        username: profileForm.username || null,
        bio: profileForm.bio || null,
      }),
    });
    if (!response.ok) {
      setStatus(response.status === 409 ? "username_taken" : "profile_error");
      return;
    }
    let user = (await response.json()) as User;
    if (avatarFile) {
      const uploadedUser = await uploadAvatarForUser(user.id);
      if (!uploadedUser) {
        return;
      }
      user = uploadedUser;
    }
    setRegisteredUser(user);
    setStatus("profile_saved");
    await loadProfile(user.id, activeView);
    await loadLeaderboard();
  }

  async function uploadAvatarForUser(userId: string): Promise<User | null> {
    if (!registeredUser || !avatarFile) {
      return null;
    }
    const formData = new FormData();
    formData.append("file", avatarFile);
    const response = await fetch(`/api/users/${userId}/avatar`, {
      method: "POST",
      headers: authHeaders(userId),
      body: formData,
    });
    if (!response.ok) {
      setStatus("avatar_error");
      return null;
    }
    const user = (await response.json()) as User;
    setAvatarFile(null);
    return user;
  }

  async function uploadAvatar() {
    if (!registeredUser) {
      return;
    }
    const user = await uploadAvatarForUser(registeredUser.id);
    if (!user) {
      return;
    }
    setRegisteredUser(user);
    setStatus("avatar_saved");
    await loadProfile(user.id, activeView);
  }

  async function unlinkTelegram() {
    if (!registeredUser) {
      return;
    }
    const response = await fetch(`/api/users/${registeredUser.id}/telegram-link`, {
      method: "DELETE",
      headers: authHeaders(registeredUser.id),
    });
    if (response.ok) {
      const user = (await response.json()) as User;
      setRegisteredUser(user);
      setTelegramCode(null);
      setStatus("telegram_unlinked");
      await loadProfile(user.id, activeView);
    }
  }

  async function unlinkVk() {
    if (!registeredUser) {
      return;
    }
    const response = await fetch(`/api/users/${registeredUser.id}/vk-link`, {
      method: "DELETE",
      headers: authHeaders(registeredUser.id),
    });
    if (response.ok) {
      const user = (await response.json()) as User;
      setRegisteredUser(user);
      setVkCode(null);
      setStatus("vk_unlinked");
      await loadProfile(user.id, activeView);
    }
  }

  async function createTelegramCode() {
    if (!registeredUser) {
      setStatus("register_first");
      return;
    }
    const response = await fetch(`/api/users/${registeredUser.id}/telegram-link-code`, {
      method: "POST",
      headers: authHeaders(registeredUser.id),
    });
    if (!response.ok) {
      setStatus("telegram_code_error");
      return;
    }
    const payload = (await response.json()) as { code: string };
    setTelegramCode(payload.code);
    setStatus("telegram_code_ready");
  }

  async function createVkCode() {
    if (!registeredUser) {
      setStatus("register_first");
      return;
    }
    const response = await fetch(`/api/users/${registeredUser.id}/vk-link-code`, {
      method: "POST",
      headers: authHeaders(registeredUser.id),
    });
    if (!response.ok) {
      setStatus("vk_code_error");
      return;
    }
    const payload = (await response.json()) as { code: string };
    setVkCode(payload.code);
    setStatus("vk_code_ready");
  }

  async function setPersonalRating(ticketId: string, degree: number) {
    const response = await fetch(`/api/tickets/${ticketId}/personal-rating`, {
      method: "PATCH",
      headers: authHeaders(profile?.user.id, { "Content-Type": "application/json" }),
      body: JSON.stringify({ degree, label: `личный класс ${degree}` }),
    });
    if (response.ok && profile) {
      await loadProfile(profile.user.id);
    }
  }

  async function deleteTicket(ticketId: string) {
    if (!profile || !registeredUser || profile.user.id !== registeredUser.id) {
      return;
    }
    const response = await fetch(`/api/tickets/${ticketId}`, {
      method: "DELETE",
      headers: authHeaders(profile.user.id),
    });
    if (!response.ok) {
      setStatus("ticket_delete_error");
      return;
    }
    setStatus("ticket_deleted");
    await loadProfile(profile.user.id, "tickets");
    await loadLeaderboard();
  }

  const selectedUserId = profile?.user.id;
  const summaryUser = profile?.user ?? registeredUser;
  const topUser = leaderboard[0];

  function authHeaders(userId?: string, extra: Record<string, string> = {}) {
    if (registeredUser?.id === userId && accessToken) {
      return { ...extra, "X-User-Token": accessToken };
    }
    return extra;
  }

  const pageTitle =
    activeView === "landing"
      ? "Старт"
      : activeView === "top"
        ? "Глобальный топ"
        : activeView === "auth"
          ? "Войти или зарегистрироваться"
          : activeView === "tickets"
            ? "Билеты"
            : activeView === "account"
              ? "Аккаунт"
              : "Статистика";

  function openLanding() {
    setActiveView("landing");
    setStatus("ready");
  }

  function openAuth() {
    setActiveView("auth");
    setStatus("ready");
  }

  function openTickets() {
    if (!registeredUser) {
      setActiveView("auth");
      setStatus("register_first");
      return;
    }
    setActiveView("tickets");
    void loadProfile(registeredUser.id, "tickets");
  }

  function openAccount() {
    if (!registeredUser) {
      setActiveView("auth");
      return;
    }
    setActiveView("account");
  }

  function renderAuthPanel() {
    return (
      <section className="auth-panel" id="register">
        {registeredUser ? (
          <>
            <div className="auth-session">
              <div className="auth-summary">
                <strong>{registeredUser.display_name}</strong>
                <div className="access-token-row">
                  <span>
                    {registeredUser.points} очков · код входа:{" "}
                    <code className="secret-value">{tokenVisible ? accessToken : maskSecret(accessToken ?? "")}</code>
                  </span>
                  <button
                    className="icon-action"
                    type="button"
                    title={tokenVisible ? "Скрыть код входа" : "Показать код входа"}
                    onClick={() => setTokenVisible((visible) => !visible)}
                  >
                    {tokenVisible ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                  <button
                    className="icon-action"
                    type="button"
                    title="Скопировать код входа"
                    onClick={() => void copyText(accessToken ?? "")}
                  >
                    {copiedValue === accessToken ? <Check size={17} /> : <Copy size={17} />}
                  </button>
                </div>
              </div>
              <button
                className="icon-action"
                type="button"
                title={registeredUser.is_profile_public ? "Скрыть профиль" : "Открыть профиль"}
                onClick={() => setPrivacy(!registeredUser.is_profile_public)}
              >
                {registeredUser.is_profile_public ? <Eye size={17} /> : <EyeOff size={17} />}
              </button>
              <button className="auth-secondary" type="button" onClick={logoutUser}>
                <LogOut size={17} />
                Выйти
              </button>
            </div>
            <AccountEditor
              user={registeredUser}
              accessToken={accessToken}
              form={profileForm}
              avatarFile={avatarFile}
              onFormChange={(patch) => setProfileForm((current) => ({ ...current, ...patch }))}
              onAvatarFileChange={setAvatarFile}
              onSaveProfile={saveProfile}
              onUploadAvatar={() => void uploadAvatar()}
              onPrivacyChange={(key, value) => void updatePrivacy({ [key]: value })}
              onCreateTelegramCode={createTelegramCode}
              onUnlinkTelegram={() => void unlinkTelegram()}
              onCreateVkCode={createVkCode}
              onUnlinkVk={() => void unlinkVk()}
              telegramCode={telegramCode}
              vkCode={vkCode}
              copiedValue={copiedValue}
              onCopy={copyText}
            />
          </>
        ) : (
          <>
            <div className="auth-tabs" role="tablist" aria-label="Вход и регистрация">
              <button
                className={authMode === "login" ? "active" : ""}
                type="button"
                onClick={() => setAuthMode("login")}
              >
                Войти
              </button>
              <button
                className={authMode === "register" ? "active" : ""}
                type="button"
                onClick={() => setAuthMode("register")}
              >
                Регистрация
              </button>
            </div>
            {authMode === "login" ? (
              <form className="auth-form" onSubmit={loginUser}>
                <input
                  value={loginToken}
                  placeholder="Код входа"
                  aria-label="Код входа"
                  onChange={(event) => setLoginToken(event.target.value)}
                />
                <button type="submit">
                  <LogIn size={17} />
                  Войти
                </button>
                <span className="profile-pill">Топ и публичные профили доступны без входа</span>
              </form>
            ) : (
              <form className="auth-form" onSubmit={registerUser}>
                <input
                  value={displayName}
                  placeholder="Имя игрока"
                  aria-label="Имя игрока"
                  onChange={(event) => setDisplayName(event.target.value)}
                />
                <button type="submit" disabled={!registerConsent}>
                  Регистрация
                </button>
                <span className="profile-pill">После регистрации сохрани код входа из аккаунта</span>
                <LegalConsentCheckbox
                  checked={registerConsent}
                  onChange={setRegisterConsent}
                  text="Я даю согласие на обработку персональных данных для регистрации профиля"
                />
              </form>
            )}
          </>
        )}
      </section>
    );
  }

  function renderTicketTools() {
    if (!registeredUser) {
      return null;
    }
    const ownTickets = profile?.user.id === registeredUser.id ? profile.tickets : [];
    const isFirstTicketUpload = registeredUser.tickets_count === 0;
    const shouldAskTicketConsent = isFirstTicketUpload && !registeredUser.personal_data_consent_given;
    return (
      <>
        <section className="tools-grid">
          <form className="ticket-submit" id="ticket-upload" onSubmit={uploadTicket}>
            <div>
              <div className="section-title">Засчитать билет</div>
              <div className="tool-note">Загрузите PDF или фото. Номер, дата и статус проверяются по файлу.</div>
            </div>
            <div className="ticket-source-actions">
              <label className={`ticket-source-action ${ticketUploading ? "disabled" : ""}`}>
                <Camera size={17} />
                Камера
                <input
                  key={`camera-${fileInputKey}`}
                  type="file"
                  accept="image/*"
                  capture="environment"
                  aria-label="Сфотографировать билет"
                  disabled={ticketUploading}
                  onChange={(event) => setTicketFile(event.target.files?.[0] ?? null)}
                />
              </label>
              <label className={`ticket-source-action ${ticketUploading ? "disabled" : ""}`}>
                <FileText size={17} />
                Файл
                <input
                  key={`file-${fileInputKey}`}
                  type="file"
                  accept="application/pdf,image/*"
                  aria-label="Выбрать PDF или фото билета"
                  disabled={ticketUploading}
                  onChange={(event) => setTicketFile(event.target.files?.[0] ?? null)}
                />
              </label>
            </div>
            {shouldAskTicketConsent ? (
              <LegalConsentCheckbox
                checked={ticketConsent}
                onChange={setTicketConsent}
                text="Я даю согласие на обработку персональных данных для загрузки первого билета"
              />
            ) : null}
            {ticketFile ? (
              <div className="ticket-preview" aria-live="polite">
                {ticketPreviewUrl ? (
                  <img src={ticketPreviewUrl} alt="Предпросмотр загруженного билета" />
                ) : (
                  <div className="ticket-preview-file">
                    <FileText size={22} />
                    <span>Файл выбран</span>
                  </div>
                )}
                <span>{ticketFile.name}</span>
              </div>
            ) : null}
            <button type="submit" disabled={ticketUploading || (shouldAskTicketConsent && !ticketConsent)}>
              {ticketUploading ? (
                <>
                  <Loader2 className="spin-icon" size={17} />
                  Проверяю билет
                </>
              ) : (
                <>
                  <UploadCloud size={17} />
                  Засчитать
                </>
              )}
            </button>
            <span className="profile-pill">
              {ticketUploading
                ? "Проверяю файл..."
                : shouldAskTicketConsent && !ticketConsent
                  ? "Сначала отметьте согласие"
                  : ticketFile
                    ? "Файл готов к отправке"
                    : "PDF, JPG, PNG или WEBP"}
            </span>
          </form>
          <ClassScaleExplainer />

        </section>
        <TicketList
          tickets={ownTickets}
          accessToken={accessToken}
          onPersonalRating={setPersonalRating}
          onDeleteTicket={deleteTicket}
        />
        <TicketGallery tickets={ownTickets} accessToken={accessToken} />
      </>
    );
  }

  function renderSummary() {
    return (
      <section className="summary-grid">
        <div className="summary-cell">
          <span>Проверенные очки</span>
          <strong>{summaryUser?.points ?? leaderboard[0]?.points ?? 0}</strong>
        </div>
        <div className="summary-cell">
          <span>Билеты</span>
          <strong>{summaryUser?.tickets_count ?? leaderboard.length}</strong>
        </div>
        <div className="summary-cell">
          <span>Проверенные</span>
          <strong>{summaryUser?.verified_tickets_count ?? "-"}</strong>
        </div>
        <div className="summary-cell">
          <span>Публичность</span>
          <strong>{profile ? (profile.user.is_profile_public ? "публичный" : "приватный") : "топ"}</strong>
        </div>
      </section>
    );
  }

  function renderContent() {
    if (activeView === "landing") {
      return (
        <Landing
          topUser={topUser}
          checkDigits={checkDigits}
          checkResult={checkResult}
          onCheckDigitsChange={setCheckDigits}
          onCheckTicketDigits={checkTicketDigits}
          onShowTop={() => void openTop()}
          onStart={() => (registeredUser ? openTickets() : openAuth())}
        />
      );
    }
    if (activeView === "auth" || activeView === "account") {
      return renderAuthPanel();
    }
    if (activeView === "tickets") {
      return renderTicketTools();
    }
    if (activeView === "profile" && profile) {
      return (
        <>
          {renderSummary()}
          <ProfileView
            profile={profile}
            isOwnProfile={registeredUser?.id === selectedUserId}
            accessToken={accessToken}
            onPersonalRating={setPersonalRating}
          />
        </>
      );
    }
    return (
      <>
        {renderSummary()}
        <Leaderboard rows={leaderboard} onOpenProfile={loadProfile} />
      </>
    );
  }

  return (
    <main className="tabbed-app" id="app">
      <header className="app-topbar">
        <div className="brand">счастливый билетик</div>
        <nav className="top-tabs" aria-label="Основные разделы">
          <button className={activeView === "landing" ? "active" : ""} type="button" onClick={openLanding}>
            Старт
          </button>
          <button className={activeView === "top" ? "active" : ""} type="button" onClick={() => void openTop()}>
            <Trophy size={17} />
            Топ
          </button>
          {registeredUser ? (
            <>
              <button
                className={activeView === "profile" && profile?.user.id === registeredUser.id ? "active" : ""}
                type="button"
                onClick={() => void loadProfile(registeredUser.id)}
              >
                <ChartNoAxesCombined size={17} />
                Статистика
              </button>
              <button className={activeView === "tickets" ? "active" : ""} type="button" onClick={openTickets}>
                <BadgeCheck size={17} />
                Билеты
              </button>
              <button className={activeView === "account" ? "active" : ""} type="button" onClick={openAccount}>
                <UserRound size={17} />
                Аккаунт
              </button>
            </>
          ) : (
            <button className={activeView === "auth" ? "active" : ""} type="button" onClick={openAuth}>
              <LogIn size={17} />
              Войти
            </button>
          )}
        </nav>
      </header>

      <section className={activeView === "landing" ? "tab-view tab-view-landing" : "workarea tab-view"}>
        {activeView !== "landing" ? (
          <header className="header">
            <h1>{pageTitle}</h1>
            <span className={`status ${statusTone(status)}`}>{statusLabels[status] ?? status}</span>
          </header>
        ) : null}
        {renderContent()}
      </section>
      <CookieNotice
        visible={!cookiesAccepted}
        onAccept={() => {
          window.localStorage.setItem("lucky-ticket-cookies", "accepted");
          setCookiesAccepted(true);
        }}
      />
    </main>
  );
}

function QuickCheckForm({
  className = "",
  checkDigits,
  checkResult,
  onCheckDigitsChange,
  onSubmit,
}: {
  className?: string;
  checkDigits: string;
  checkResult: HappinessResult | null;
  onCheckDigitsChange: (value: string) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form className={`quick-check ${className}`.trim()} onSubmit={onSubmit}>
      <div>
        <div className="section-title">Быстрая проверка</div>
        <div className="tool-note">Введите последние 4 цифры билета. Это не засчитывает билет в топ.</div>
      </div>
      <div className="check-row">
        <input
          inputMode="numeric"
          pattern="[0-9]*"
          maxLength={4}
          value={checkDigits}
          placeholder="0889"
          aria-label="Последние 4 цифры билета"
          onChange={(event) => onCheckDigitsChange(event.target.value.replace(/\D/g, "").slice(0, 4))}
        />
        <button type="submit" title="Проверить 4 цифры">
          <Search size={17} />
        </button>
      </div>
      {checkResult ? (
        <div className="check-result">
          <strong>Класс {checkResult.degree}</strong>
          <span>
            {checkResult.label} · {checkResult.points} очков
          </span>
        </div>
      ) : null}
      <ClassScaleExplainer />
    </form>
  );
}

function LegalConsentCheckbox({
  checked,
  onChange,
  text,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  text: string;
}) {
  return (
    <label className="legal-consent">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>
        {text}. Ознакомлен(а) с{" "}
        <a href={LEGAL_LINKS.personalDataPolicy} target="_blank" rel="noreferrer">
          политикой обработки персональных данных
        </a>{" "}
        и{" "}
        <a href={LEGAL_LINKS.personalDataConsent} target="_blank" rel="noreferrer">
          согласием на обработку персональных данных
        </a>
        .
      </span>
    </label>
  );
}

function CookieNotice({ visible, onAccept }: { visible: boolean; onAccept: () => void }) {
  if (!visible) {
    return null;
  }

  return (
    <aside className="cookie-notice" aria-live="polite">
      <div>
        <strong>Cookies и Метрика</strong>
        <span>
          Сайт использует cookies и Яндекс Метрику для аналитики, улучшения работы сервиса и понятной статистики.
        </span>
      </div>
      <button type="button" onClick={onAccept}>
        Понятно
      </button>
    </aside>
  );
}

function ClassScaleExplainer() {
  const rows = [
    ["Класс 0", "Классический счастливый: суммы левой и правой половины сразу равны. Это максимум очков."],
    ["Класс 1", "Счастливый после одной свертки: половинки сходятся после одного сложения цифр."],
    ["Класс 2", "Редкий промежуточный класс для личной оценки и особых правил."],
    ["Класс 3", "Счастливый после двойной свертки: например, 0889 справа считается как 8+9=17, затем 1+7=8."],
    ["Класс 4", "Пасхалки: красивые, культурно значимые числа, палиндромы и похожие находки."],
    ["Класс 5", "Обычный билет без счастливого совпадения."],
  ];

  return (
    <details className="class-scale">
      <summary>Как считаются классы</summary>
      <div className="class-scale-list">
        {rows.map(([title, description]) => (
          <div className="class-scale-row" key={title}>
            <strong>{title}</strong>
            <span>{description}</span>
          </div>
        ))}
      </div>
    </details>
  );
}

function AccountEditor({
  user,
  accessToken,
  form,
  avatarFile,
  telegramCode,
  vkCode,
  copiedValue,
  onFormChange,
  onAvatarFileChange,
  onSaveProfile,
  onUploadAvatar,
  onPrivacyChange,
  onCreateTelegramCode,
  onUnlinkTelegram,
  onCreateVkCode,
  onUnlinkVk,
  onCopy,
}: {
  user: User;
  accessToken: string | null;
  form: ProfileFormState;
  avatarFile: File | null;
  telegramCode: string | null;
  vkCode: string | null;
  copiedValue: string | null;
  onFormChange: (patch: Partial<ProfileFormState>) => void;
  onAvatarFileChange: (file: File | null) => void;
  onSaveProfile: (event: React.FormEvent<HTMLFormElement>) => void;
  onUploadAvatar: () => void;
  onPrivacyChange: (key: string, value: boolean) => void;
  onCreateTelegramCode: () => void;
  onUnlinkTelegram: () => void;
  onCreateVkCode: () => void;
  onUnlinkVk: () => void;
  onCopy: (value: string) => void | Promise<void>;
}) {
  const privacy = withDefaultPrivacy(user.privacy_settings);
  const linkCommand = telegramCode ? `/link ${telegramCode}` : "";
  const vkLinkCommand = vkCode ? `/link ${vkCode}` : "";
  const avatarPreviewUrl = useMemo(
    () => (avatarFile ? URL.createObjectURL(avatarFile) : avatarSrc(user, accessToken)),
    [avatarFile, user, accessToken],
  );

  useEffect(() => {
    if (!avatarFile) {
      return;
    }
    return () => URL.revokeObjectURL(avatarPreviewUrl);
  }, [avatarFile, avatarPreviewUrl]);

  return (
    <section className="account-grid">
      <form className="account-card profile-edit-form" onSubmit={onSaveProfile}>
        <div className="profile-edit-head">
          <div className="avatar-upload-frame">
            <label className="avatar-upload-target">
              <img className="profile-avatar" src={avatarPreviewUrl} alt="" />
              <input
                type="file"
                accept="image/*"
                aria-label="Файл аватарки"
                onChange={(event) => onAvatarFileChange(event.target.files?.[0] ?? null)}
              />
              <span>
                <UploadCloud size={16} />
                Заменить
              </span>
            </label>
            {avatarFile ? (
              <button type="button" onClick={onUploadAvatar}>
                Загрузить
              </button>
            ) : null}
          </div>
          <div>
            <div className="section-title">Профиль</div>
            <div className="tool-note">Имя, юзернейм и био.</div>
          </div>
        </div>
        <input
          value={form.display_name}
          placeholder="Имя"
          aria-label="Имя"
          onChange={(event) => onFormChange({ display_name: event.target.value })}
        />
        <input
          value={form.username}
          placeholder="username"
          aria-label="Юзернейм"
          onChange={(event) => onFormChange({ username: event.target.value.replace(/^@/, "") })}
        />
        <textarea
          value={form.bio}
          placeholder="О себе"
          aria-label="О себе"
          onChange={(event) => onFormChange({ bio: event.target.value })}
        />
        <button type="submit">Сохранить профиль</button>
      </form>

      <section className="account-card">
        <div className="section-title">Приватность</div>
        <PrivacyToggle label="Профиль виден в топе" checked={user.is_profile_public} onChange={(value) => onPrivacyChange("is_profile_public", value)} />
        <PrivacyToggle label="О себе и аватарка" checked={privacy.show_about} onChange={(value) => onPrivacyChange("show_about", value)} />
        <PrivacyToggle label="Графики и статистика" checked={privacy.show_stats} onChange={(value) => onPrivacyChange("show_stats", value)} />
        <PrivacyToggle label="Список билетов" checked={privacy.show_tickets} onChange={(value) => onPrivacyChange("show_tickets", value)} />
        <PrivacyToggle label="Фото билетов" checked={privacy.show_photos} onChange={(value) => onPrivacyChange("show_photos", value)} />
      </section>

      {user.ticket_mail_address ? (
        <section className="account-card ticket-mail-card">
          <div>
            <div className="section-title">Билеты из Мир Транспорт</div>
            <div className="tool-note">Укажите этот E-mail в личном кабинете bilet.nspk.ru для отправки билетов.</div>
          </div>
          <CopyField
            value={user.ticket_mail_address}
            label="E-mail для билетов"
            copied={copiedValue === user.ticket_mail_address}
            onCopy={onCopy}
          />
        </section>
      ) : null}

      <section className="account-card social-links-card">
        <div>
          <div className="section-title">Соцсети</div>
          <div className="tool-note">Привязка Telegram и VK для ботов, входа и отправки билетов из чата.</div>
        </div>
        <div className="social-links-grid">
          <div className="social-link-block">
            <div className="social-link-head">
              <MessengerIcon provider="telegram" />
              <strong>Telegram</strong>
            </div>
            <div className="tool-note">
              {user.telegram_linked
                ? `Сейчас привязан ${user.telegram_username ? `@${user.telegram_username}` : "аккаунт"}. Можно отвязать и привязать другой.`
                : "Получите команду и отправьте ее боту."}
            </div>
            <PrivacyToggle label="Показывать Telegram-тэг публично" checked={privacy.show_telegram} onChange={(value) => onPrivacyChange("show_telegram", value)} />
            <div className="button-row">
              <button type="button" onClick={onCreateTelegramCode}>
                <Link2 size={17} />
                Получить код
              </button>
              {user.telegram_linked ? (
                <button type="button" onClick={onUnlinkTelegram}>
                  Отвязать
                </button>
              ) : null}
            </div>
            {telegramCode ? (
              <CopyField value={linkCommand} label="Команда для бота" copied={copiedValue === linkCommand} onCopy={onCopy} />
            ) : null}
          </div>

          <div className="social-link-block">
            <div className="social-link-head">
              <MessengerIcon provider="vk" />
              <strong>VK</strong>
            </div>
            <div className="tool-note">
              {user.vk_linked
                ? `Сейчас привязан ${user.vk_username ? `@${user.vk_username}` : "аккаунт"}. Можно отвязать и привязать другой.`
                : "Получите команду и отправьте ее VK-боту в сообщения сообщества."}
            </div>
            <PrivacyToggle label="Показывать VK-тэг публично" checked={privacy.show_vk} onChange={(value) => onPrivacyChange("show_vk", value)} />
            <div className="button-row">
              <button type="button" onClick={onCreateVkCode}>
                <Link2 size={17} />
                Получить код
              </button>
              {user.vk_linked ? (
                <button type="button" onClick={onUnlinkVk}>
                  Отвязать
                </button>
              ) : null}
            </div>
            {vkCode ? (
              <CopyField value={vkLinkCommand} label="Команда для VK-бота" copied={copiedValue === vkLinkCommand} onCopy={onCopy} />
            ) : null}
          </div>
        </div>
      </section>
    </section>
  );
}

function PrivacyToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="privacy-toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

function TicketGallery({ tickets, accessToken }: { tickets: Ticket[]; accessToken: string | null }) {
  const imageTickets = tickets.filter((ticket) => ticket.image_url);
  return (
    <section className="ticket-gallery">
      <div className="section-title">Фото билетов</div>
      {imageTickets.length === 0 ? (
        <div className="empty-chart">фото пока нет</div>
      ) : (
        <div className="ticket-gallery-grid">
          {imageTickets.map((ticket) => (
            <article className="ticket-photo-card" key={ticket.id}>
              <img src={ticketImageSrc(ticket, accessToken)} alt={`Билет ${ticket.ticket_number.slice(-4)}`} />
              <div>
                <strong>{ticket.ticket_number.slice(-4)}</strong>
                <span>{formatTicketDateTime(ticket)} · класс {ticket.official_degree}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function TicketList({
  tickets,
  accessToken,
  onPersonalRating,
  onDeleteTicket,
}: {
  tickets: Ticket[];
  accessToken: string | null;
  onPersonalRating: (ticketId: string, degree: number) => void;
  onDeleteTicket: (ticketId: string) => void;
}) {
  return (
    <section className="table-section ticket-list-section">
      <div className="section-title">Билетики</div>
      <table>
        <thead>
          <tr>
            <th>Фото</th>
            <th>День</th>
            <th>Номер</th>
            <th>Статус</th>
            <th>Класс</th>
            <th>Очки</th>
            <th>Личный</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {tickets.length === 0 ? (
            <tr>
              <td colSpan={8}>Билетиков пока нет.</td>
            </tr>
          ) : null}
          {tickets.map((ticket) => (
            <tr key={ticket.id}>
              <td data-label="Фото">
                {ticket.image_url ? (
                  <img className="ticket-thumb" src={ticketImageSrc(ticket, accessToken)} alt="" />
                ) : (
                  "-"
                )}
              </td>
              <td data-label="День">{formatTicketDateTime(ticket)}</td>
              <td className="mono" data-label="Номер">{ticket.ticket_number.slice(-4)}</td>
              <td data-label="Статус">
                <span className={`ticket-status ${ticketStatusTone(ticket.status)}`}>
                  {ticketStatusLabels[ticket.status] ?? ticket.status}
                </span>
              </td>
              <td data-label="Класс">{ticket.official_degree}</td>
              <td data-label="Очки">{ticket.official_points}</td>
              <td data-label="Личный">
                <select
                  value={ticket.personal_degree ?? ticket.official_degree}
                  onChange={(event) => onPersonalRating(ticket.id, Number(event.target.value))}
                  aria-label="Личный класс"
                >
                  {[0, 1, 2, 3, 4, 5].map((degree) => (
                    <option key={degree} value={degree}>
                      {degree}
                    </option>
                  ))}
                </select>
              </td>
              <td data-label="">
                {ticket.status !== "verified" ? (
                  <button
                    className="icon-action danger-action"
                    type="button"
                    title="Удалить непроверенный билет"
                    onClick={() => onDeleteTicket(ticket.id)}
                  >
                    <Trash2 size={17} />
                  </button>
                ) : (
                  "-"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function CopyField({
  value,
  label,
  copied,
  onCopy,
  openable = false,
}: {
  value: string;
  label: string;
  copied: boolean;
  onCopy: (value: string) => void | Promise<void>;
  openable?: boolean;
}) {
  return (
    <div className="copy-field">
      <span>{label}</span>
      <code>{value}</code>
      <button type="button" title="Скопировать" onClick={() => void onCopy(value)}>
        {copied ? <Check size={17} /> : <Copy size={17} />}
      </button>
      {openable ? (
        <a href={value} title="Открыть" aria-label="Открыть">
          <ExternalLink size={17} />
        </a>
      ) : null}
    </div>
  );
}

function Landing({
  topUser,
  checkDigits,
  checkResult,
  onCheckDigitsChange,
  onCheckTicketDigits,
  onShowTop,
  onStart,
}: {
  topUser?: User;
  checkDigits: string;
  checkResult: HappinessResult | null;
  onCheckDigitsChange: (value: string) => void;
  onCheckTicketDigits: (event: React.FormEvent<HTMLFormElement>) => void;
  onShowTop: () => void;
  onStart: () => void;
}) {
  return (
    <section className="landing">
      <div className="landing-grid">
        <div className="landing-copy">
          <span className="eyebrow">Городская игра на билетиках</span>
          <h1>Проверяй счастливость билетов и собирай свой дневной график</h1>
          <p>
            Быстро проверь последние 4 цифры или загрузи настоящий PDF/фото билета после регистрации. Сервис
            распознает номер, раскладывает поездки по датам, считает очки и строит топ только по проверенным билетам.
          </p>
          <QuickCheckForm
            className="landing-check"
            checkDigits={checkDigits}
            checkResult={checkResult}
            onCheckDigitsChange={onCheckDigitsChange}
            onSubmit={onCheckTicketDigits}
          />
          <div className="landing-cta">
            <button className="dark-action" type="button" onClick={onStart}>
              Начать
            </button>
            <button type="button" onClick={onShowTop}>
              Смотреть топ
            </button>
          </div>
        </div>

        <div className="ticket-stage" aria-hidden="true">
          <div className="route-line">
            <span />
            <span />
            <span />
          </div>
          <div className="ticket-stack">
            <div className="ticket-card ticket-one">
              <span>4 цифры</span>
              <strong>0369</strong>
              <small>быстрая проверка</small>
            </div>
            <div className="ticket-card ticket-two">
              <span>PDF или фото</span>
              <strong>QR</strong>
              <small>зачет в профиль</small>
            </div>
            <div className="ticket-card ticket-three">
              <span>Топ</span>
              <strong>{topUser ? topUser.points : 0}</strong>
              <small>{topUser ? topUser.display_name : "появится здесь"}</small>
            </div>
          </div>
        </div>
      </div>

      <div className="feature-strip">
        <div>
          <strong>Без регистрации</strong>
          <span>смотрите топ, публичные профили и проверка своих билетов</span>
        </div>
        <div>
          <strong>Настоящие билеты</strong>
          <span>для зачета нужен PDF или фото, один билет нельзя добавить дважды</span>
        </div>
        <div>
          <strong>Telegram и VK</strong>
          <span>аккаунты можно привязать и присылать билет прямо в чат</span>
        </div>
      </div>
    </section>
  );
}

function Leaderboard({ rows, onOpenProfile }: { rows: User[]; onOpenProfile: (id: string) => void }) {
  return (
    <section className="table-section">
      <div className="section-title">Глобальный топ: только проверенные билеты</div>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Пользователь</th>
            <th>Проверенные</th>
            <th>Очки</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4}>Пока нет проверенных публичных профилей.</td>
            </tr>
          ) : null}
          {rows.map((user, index) => (
          <tr key={user.id}>
            <td data-label="#">{index + 1}</td>
            <td data-label="Пользователь">
              <div className="leader-user">
                <button className="link-button" type="button" onClick={() => onOpenProfile(user.id)}>
                  {user.display_name}
                </button>
                <MessengerBadges user={user} compact />
              </div>
            </td>
            <td data-label="Проверенные">{user.verified_tickets_count}</td>
            <td data-label="Очки">{user.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ProfileHeader({ profile, accessToken }: { profile: Profile; accessToken: string | null }) {
  const user = profile.user;
  return (
    <section className="profile-hero">
      <img className="profile-avatar profile-avatar-large" src={avatarSrc(user, accessToken)} alt="" />
      <div>
        <div className="section-title">Статистика</div>
        <h2>{user.display_name}</h2>
        <div className="profile-meta">
          {user.username ? <span>@{user.username}</span> : null}
          <MessengerBadges user={user} />
        </div>
        {user.bio ? <p>{user.bio}</p> : null}
      </div>
    </section>
  );
}

function MessengerBadges({ user, compact = false }: { user: User; compact?: boolean }) {
  const privacy = withDefaultPrivacy(user.privacy_settings);
  const items = [
    user.telegram_linked && privacy.show_telegram
      ? {
          provider: "telegram" as const,
          label: user.telegram_username ? `Telegram: @${user.telegram_username}` : "Telegram",
          text: user.telegram_username ? `Telegram: @${user.telegram_username}` : "Telegram",
        }
      : null,
    user.vk_linked && privacy.show_vk
      ? {
          provider: "vk" as const,
          label: user.vk_username ? `VK: @${user.vk_username}` : "VK",
          text: user.vk_username ? `VK: @${user.vk_username}` : "VK",
        }
      : null,
  ].filter(Boolean) as Array<{ provider: "telegram" | "vk"; label: string; text: string | null }>;

  if (items.length === 0) {
    return null;
  }

  return (
    <span className={compact ? "messenger-badges compact" : "messenger-badges"}>
      {items.map((item) => (
        <span className={`messenger-badge ${item.provider}`} key={item.provider} title={item.label}>
          <MessengerIcon provider={item.provider} />
          {!compact && item.text ? <span>{item.text}</span> : null}
        </span>
      ))}
    </span>
  );
}

function MessengerIcon({ provider }: { provider: "telegram" | "vk" }) {
  if (provider === "telegram") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M21.4 4.1 18.2 19c-.2 1-.8 1.2-1.6.8l-4.5-3.3-2.1 2c-.3.3-.5.5-1 .5l.4-4.7 8.6-7.8c.4-.3-.1-.5-.6-.2L6.8 13 2.2 11.5c-1-.3-1-1 .2-1.4L20.1 3.3c.9-.3 1.6.2 1.3.8Z" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3.4 6.4c.1 5.8 3 9.3 8.4 9.3h.3v-3.3c1.9.2 3.3 1.6 3.9 3.3h3.1c-.8-2.6-2.7-4.1-3.9-4.7 1.2-.8 2.9-2.5 3.3-4.6h-2.9c-.5 1.8-2.1 3.5-3.5 3.7V6.4H9.2v6.4C7.7 12.4 5.9 10.6 5.8 6.4H3.4Z" />
    </svg>
  );
}

function ProfileView({
  profile,
  isOwnProfile,
  accessToken,
  onPersonalRating,
}: {
  profile: Profile;
  isOwnProfile: boolean;
  accessToken: string | null;
  onPersonalRating: (ticketId: string, degree: number) => void;
}) {
  const latestDay = profile.daily_stats[profile.daily_stats.length - 1]?.day;
  const hourlySeries = buildHourlyChartSeries(profile.hourly_stats, latestDay);

  return (
    <>
      <ProfileHeader profile={profile} accessToken={isOwnProfile ? accessToken : null} />
      <section className="charts-grid">
        <HappinessChart
          title="Официальная счастливость"
          subtitle="Средний класс билетов за день"
          series={profile.daily_stats.map((point) => ({
            day: point.day,
            value: point.official_happiness,
            points: point.official_points,
            tickets: point.tickets_count,
            bestTicket: point.best_ticket,
            bestDegree: point.best_degree,
          }))}
          accent="#111111"
        />
        <HappinessChart
          title="Личная шкала"
          subtitle="С учетом твоей переоценки классов"
          series={profile.daily_stats.map((point) => ({
            day: point.day,
            value: point.personal_happiness,
            points: point.personal_points,
            tickets: point.tickets_count,
            bestTicket: point.best_ticket,
            bestDegree: point.best_degree,
          }))}
          accent="#2f6f73"
        />
      </section>

      <section className="wide-chart">
        <HappinessChart
          title={latestDay ? `День по часам · ${latestDay}` : "День по часам"}
          subtitle="Средняя счастливость в каждый час поездок"
          series={hourlySeries}
          accent="#7a4d1d"
        />
      </section>

      <section className="table-section">
        <div className="section-title">Билеты профиля</div>
        <table>
          <thead>
            <tr>
              <th>Фото</th>
              <th>День</th>
              <th>Номер</th>
              <th>Статус</th>
              <th>Класс</th>
              <th>Личный</th>
            </tr>
          </thead>
          <tbody>
            {profile.tickets.length === 0 ? (
              <tr>
                <td colSpan={6}>Билетов пока нет.</td>
              </tr>
            ) : null}
            {profile.tickets.map((ticket) => (
              <tr key={ticket.id}>
                <td>
                  {ticket.image_url ? (
                    <img className="ticket-thumb" src={ticketImageSrc(ticket, isOwnProfile ? accessToken : null)} alt="" />
                  ) : (
                    "-"
                  )}
                </td>
                <td>{formatTicketDateTime(ticket)}</td>
                <td className="mono">{ticket.ticket_number.slice(-4)}</td>
                <td>
                  <span className={`ticket-status ${ticketStatusTone(ticket.status)}`}>
                    {ticketStatusLabels[ticket.status] ?? ticket.status}
                  </span>
                </td>
                <td>{ticket.official_degree}</td>
                <td>
                  {isOwnProfile ? (
                    <select
                      value={ticket.personal_degree ?? ticket.official_degree}
                      onChange={(event) => onPersonalRating(ticket.id, Number(event.target.value))}
                    >
                      {[0, 1, 2, 3, 4, 5].map((degree) => (
                        <option key={degree} value={degree}>
                          {degree}
                        </option>
                      ))}
                    </select>
                  ) : (
                    (ticket.personal_degree ?? "-")
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function buildHourlyChartSeries(points: HourlyStatsPoint[], day?: string): ChartPoint[] {
  if (!day) {
    return [];
  }
  const dayPoints = points.filter((point) => point.day === day);
  if (dayPoints.length === 0) {
    return [];
  }
  const byHour = new Map(dayPoints.map((point) => [point.hour, point]));
  const minHour = Math.min(...dayPoints.map((point) => point.hour));
  const maxHour = Math.max(...dayPoints.map((point) => point.hour));
  return Array.from({ length: maxHour - minHour + 1 }, (_, index) => {
    const hour = minHour + index;
    const point = byHour.get(hour);
    return {
      day: `${hour.toString().padStart(2, "0")}:00`,
      value: point?.official_happiness ?? 0,
      points: point?.official_points ?? 0,
      tickets: point?.tickets_count ?? 0,
      bestTicket: point?.best_ticket ?? null,
      bestDegree: point?.best_degree ?? null,
    };
  });
}

function statusTone(status: string): string {
  if (status.endsWith("_error") || status === "login_error" || status === "ticket_parse_error") {
    return "status-danger";
  }
  if (status.includes("loading") || status.includes("uploading") || status.includes("code_ready")) {
    return "status-warn";
  }
  if (status === "ready" || status === "logged_out") {
    return "status-neutral";
  }
  return "status-success";
}

function ticketStatusTone(status: string): string {
  if (status === "verified") {
    return "ticket-status-success";
  }
  if (status === "pending_check" || status === "parsed") {
    return "ticket-status-warn";
  }
  if (status === "not_found" || status === "check_error") {
    return "ticket-status-danger";
  }
  return "ticket-status-neutral";
}

function parseAppView(value: string | null): AppView | null {
  if (value === "landing" || value === "top" || value === "auth" || value === "profile" || value === "tickets" || value === "account") {
    return value;
  }
  return null;
}

function withDefaultPrivacy(value: Record<string, boolean> | null | undefined): Record<string, boolean> {
  return {
    show_about: value?.show_about ?? true,
    show_stats: value?.show_stats ?? true,
    show_tickets: value?.show_tickets ?? true,
    show_photos: value?.show_photos ?? false,
    show_telegram: value?.show_telegram ?? true,
    show_vk: value?.show_vk ?? true,
  };
}

function avatarSrc(user: User, accessToken: string | null): string {
  if (!user.avatar_url) {
    const initial = encodeURIComponent(user.display_name.trim().slice(0, 1).toUpperCase() || "?");
    return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 96 96'%3E%3Crect width='96' height='96' fill='%23f3f1ea'/%3E%3Ctext x='48' y='58' text-anchor='middle' font-size='34' font-family='Arial' font-weight='700' fill='%23111111'%3E${initial}%3C/text%3E%3C/svg%3E`;
  }
  if (user.avatar_url.startsWith("/api/") && accessToken) {
    return withQueryParam(user.avatar_url, "token", accessToken);
  }
  return user.avatar_url;
}

function ticketImageSrc(ticket: Ticket, accessToken: string | null): string {
  if (!ticket.image_url) {
    return "";
  }
  if (accessToken) {
    return withQueryParam(ticket.image_url, "token", accessToken);
  }
  return ticket.image_url;
}

function withQueryParam(url: string, key: string, value: string): string {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}${encodeURIComponent(key)}=${encodeURIComponent(value)}`;
}

function isPreviewableImage(file: File): boolean {
  return file.type.startsWith("image/") || /\.(avif|bmp|gif|jpe?g|png|webp)$/i.test(file.name);
}

function maskSecret(value: string): string {
  if (!value) {
    return "";
  }
  if (value.length <= 8) {
    return "••••";
  }
  return `${value.slice(0, 4)}***${value.slice(-4)}`;
}

function formatTicketDateTime(ticket: Ticket): string {
  if (!ticket.purchased_at) {
    return ticket.day;
  }
  const match = ticket.purchased_at.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : ticket.day;
}

type ChartPoint = {
  day: string;
  value: number;
  points: number;
  tickets: number;
  bestTicket: string | null;
  bestDegree: number | null;
};

function chartPointTitle(point: ChartPoint): string {
  return [
    point.day,
    `Счастливость: ${point.value.toFixed(1)}`,
    `Билетов: ${point.tickets}`,
    `Очков: ${point.points}`,
    point.bestTicket ? `Лучший билет: ${point.bestTicket}` : "Лучший билет: нет",
    point.bestDegree === null ? null : `Класс: ${point.bestDegree}`,
  ]
    .filter((line): line is string => line !== null)
    .join("\n");
}

function HappinessChart({
  title,
  subtitle,
  series,
  accent,
}: {
  title: string;
  subtitle: string;
  series: ChartPoint[];
  accent: string;
}) {
  const width = 520;
  const height = 220;
  const padding = { top: 20, right: 18, bottom: 36, left: 34 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const points = useMemo(() => {
    if (series.length === 0) {
      return [];
    }
    const denominator = Math.max(1, series.length - 1);
    return series.map((point, index) => ({
      ...point,
      x: padding.left + (plotWidth * index) / denominator,
      y: padding.top + plotHeight - (Math.min(5, Math.max(0, point.value)) / 5) * plotHeight,
    }));
  }, [plotHeight, plotWidth, series]);
  const path = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
  const firstPoint = points[0];
  const lastPoint = points.length ? points[points.length - 1] : undefined;
  const areaPath = path
    ? `${path} L ${lastPoint?.x.toFixed(2)} ${padding.top + plotHeight} L ${firstPoint.x.toFixed(2)} ${padding.top + plotHeight} Z`
    : "";
  const latest = lastPoint;
  const average = series.length
    ? series.reduce((total, point) => total + point.value, 0) / series.length
    : 0;

  return (
    <section className="chart-block">
      <div className="chart-head">
        <div>
          <div className="section-title">{title}</div>
          <p>{subtitle}</p>
        </div>
        <strong>{average.toFixed(1)}</strong>
      </div>
      {series.length === 0 ? (
        <div className="empty-chart">нет данных</div>
      ) : (
        <>
          <svg className="line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
            {[0, 1, 2, 3, 4, 5].map((tick) => {
              const y = padding.top + plotHeight - (tick / 5) * plotHeight;
              return (
                <g key={tick}>
                  <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
                  <text x={10} y={y + 4}>
                    {tick}
                  </text>
                </g>
              );
            })}
            {areaPath ? <path className="chart-area" d={areaPath} style={{ fill: accent }} /> : null}
            {path ? <path className="chart-line" d={path} style={{ stroke: accent }} /> : null}
            {points.map((point) => {
              const pointTitle = chartPointTitle(point);
              return (
                <g key={point.day} aria-label={pointTitle}>
                  <title>{pointTitle}</title>
                  <circle className="chart-dot" cx={point.x} cy={point.y} r="4.5" style={{ fill: accent }} />
                  <text className="chart-label" x={point.x} y={height - 10}>
                    {point.day.slice(5)}
                  </text>
                </g>
              );
            })}
          </svg>
          <div className="chart-meta">
            <span>Последний день: {latest?.value.toFixed(1) ?? "0.0"}</span>
            <span>Билетов: {latest?.tickets ?? 0}</span>
            <span>Очков: {latest?.points ?? 0}</span>
            <span>Лучший: {latest?.bestTicket ? `${latest.bestTicket} · класс ${latest.bestDegree}` : "-"}</span>
          </div>
        </>
      )}
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);

import os
import re
import json
import secrets
import hashlib
import hmac
import streamlit as st
from pathlib import Path
from PIL import Image
from typing import List, Dict, Any
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    import config as app_config
except Exception:
    app_config = None


try:
    import mysql.connector
    from mysql.connector import Error
    MYSQL_AVAILABLE = True
except Exception:
    MYSQL_AVAILABLE = False

try:
    from sqlalchemy import create_engine, inspect, text
    SQLALCHEMY_AVAILABLE = True
except Exception:
    SQLALCHEMY_AVAILABLE = False

try:
    import pymysql
    import pymysql.cursors
    PYMYSQL_AVAILABLE = True
except Exception:
    PYMYSQL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Server-side session cache for 20-minute Discord login persistence.
# Keyed by a random URL-safe token stored in st.query_params["session"].
# ---------------------------------------------------------------------------
_SESSION_CACHE: Dict[str, Any] = {}
SESSION_TTL_SECONDS = 20 * 60  # 20 minutes

# SHA-256 hash of the thesis-advisor access password (never stored as plaintext).
_ADVISOR_PW_HASH: str = hashlib.sha256(b"VS_CSA3D1").hexdigest()


def _prune_session_cache() -> None:
    """Remove expired entries from the in-memory session cache."""
    now = datetime.now(timezone.utc)
    expired = [k for k, v in list(_SESSION_CACHE.items()) if v["expires_at"] < now]
    for k in expired:
        del _SESSION_CACHE[k]


DEFAULT_TRANSCRIPT_DIRS = ["transcripts", "logs"]
DEFAULT_IMAGE_DIRS = ["transcripts/images", "logs/images", "images"]
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTH_URL = "https://discord.com/oauth2/authorize"
CCAC_MAIN_GUILD_ID = 1240448660266029126
CCAC_ALLOWED_ROLE_IDS = {
    1334289756539846656,  # Jr. mod
    1243559774847766619,  # mod
    1243929060145631262,  # admin
    1240455108047671406,  # owner
    1243929202785386527,  # tech
}

# Roles permitted to manage premade messages via the Streamlit UI
CCAC_ADMIN_ROLE_IDS = {
    1243929060145631262,  # admin
    1240455108047671406,  # owner
    1243929202785386527,  # tech
}


def is_admin_user(discord_auth: dict) -> bool:
    """Return True if the authenticated user holds an admin-or-higher role."""
    role_ids = set(discord_auth.get("role_ids") or [])
    return bool(role_ids.intersection(CCAC_ADMIN_ROLE_IDS))


# Tech role – subset of admin that also gets the Bot Config Editor
CCAC_TECH_ROLE_IDS = {
    1243929202785386527,  # tech
}

# Human-readable display names for all staff role IDs
CCAC_ROLE_NAMES: Dict[int, str] = {
    1334289756539846656: "Jr. Mod",
    1243559774847766619: "Mod",
    1243929060145631262: "Admin",
    1240455108047671406: "Owner",
    1243929202785386527: "Tech",
}


def is_tech_user(discord_auth: dict) -> bool:
    """Return True if the authenticated user holds the tech role."""
    role_ids = set(discord_auth.get("role_ids") or [])
    return bool(role_ids.intersection(CCAC_TECH_ROLE_IDS))


APP_ROOT = Path(__file__).resolve().parent

# MySQL Database configuration (same as bot)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "gameswaw5.bisecthosting.com"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u1079393_bwVUJntzFf"),
    "password": os.getenv("DB_PASS", "XzaXNWotYim7AWlIeudHjSoO"),
    "database": os.getenv("DB_NAME", "s1079393_ModMail"),
}

DIXIE_DB_CONFIG = {
    "host": os.getenv("DIXIE_DB_HOST", "gameswaw1.bisecthosting.com"),
    "port": int(os.getenv("DIXIE_DB_PORT", "3306")),
    "user": os.getenv("DIXIE_DB_USER", "u404394_zpDXmPyRMs"),
    "password": os.getenv("DIXIE_DB_PASS", "s8HvVfGoqUpl9LRGVShnqzOk"),
    "database": os.getenv("DIXIE_DB_NAME", "s404394_DixieModerator"),
}

if load_dotenv is not None:
    load_dotenv(APP_ROOT / ".env")


def get_secret_value(key: str, default: str = "") -> str:
    try:
        value = st.secrets.get(key) if hasattr(st, "secrets") else None
    except Exception:
        value = None
    if value in (None, ""):
        return default
    return str(value).strip()


def http_json(url: str, *, method: str = "GET", headers: Dict[str, str] = None, data: bytes = None) -> Dict[str, Any]:
    merged_headers = {
        "User-Agent": "DiscordBot (https://ccac-moussemail.streamlit.app, 1.0)",
    }
    if headers:
        merged_headers.update(headers)
    req = Request(url, data=data, headers=merged_headers, method=method)
    with urlopen(req, timeout=20) as response:
        payload = response.read().decode("utf-8")
        return json.loads(payload) if payload else {}


def get_discord_oauth_settings() -> Dict[str, str]:
    config_client_id = getattr(app_config, "DISCORD_CLIENT_ID", "") if app_config else ""
    config_client_secret = getattr(app_config, "DISCORD_CLIENT_SECRET", "") if app_config else ""
    config_redirect_uri = getattr(app_config, "DISCORD_REDIRECT_URI", "") if app_config else ""

    client_id = str(os.getenv("DISCORD_CLIENT_ID") or get_secret_value("DISCORD_CLIENT_ID") or config_client_id or "").strip()
    client_secret = str(os.getenv("DISCORD_CLIENT_SECRET") or get_secret_value("DISCORD_CLIENT_SECRET") or config_client_secret or "").strip()
    redirect_uri = str(
        os.getenv("DISCORD_REDIRECT_URI")
        or get_secret_value("DISCORD_REDIRECT_URI")
        or config_redirect_uri
        or os.getenv("STREAMLIT_PUBLIC_URL", "")
        or get_secret_value("STREAMLIT_PUBLIC_URL")
    ).strip()
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def get_bot_token() -> str:
    config_bot_token = getattr(app_config, "DISCORD_BOT_TOKEN", "") if app_config else ""
    return str(
        os.getenv("DISCORD_BOT_TOKEN")
        or get_secret_value("DISCORD_BOT_TOKEN")
        or config_bot_token
        or ""
    ).strip()


def build_discord_login_url(state: str) -> str:
    settings = get_discord_oauth_settings()
    params = {
        "client_id": settings["client_id"],
        "redirect_uri": settings["redirect_uri"],
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent",
    }
    return f"{DISCORD_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> Dict[str, Any]:
    settings = get_discord_oauth_settings()
    payload = urlencode(
        {
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings["redirect_uri"],
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "DiscordBot (https://ccac-moussemail.streamlit.app, 1.0)",
    }
    return http_json(f"{DISCORD_API_BASE}/oauth2/token", method="POST", headers=headers, data=payload)


def fetch_discord_user(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    return http_json(f"{DISCORD_API_BASE}/users/@me", headers=headers)


def fetch_member_roles(user_id: str) -> set:
    """Use the bot token to look up the user's roles in the CCAC guild."""
    bot_token = get_bot_token()
    if not bot_token:
        return set()
    headers = {"Authorization": f"Bot {bot_token}"}
    try:
        member = http_json(
            f"{DISCORD_API_BASE}/guilds/{CCAC_MAIN_GUILD_ID}/members/{user_id}",
            headers=headers,
        )
        return {int(r) for r in member.get("roles", [])}
    except Exception:
        return set()


@st.cache_data(ttl=300)
def fetch_current_staff_usernames() -> set:
    """Return the set of lowercase usernames of members who currently hold a staff role.

    Paginates through the guild member list (up to 5 000 members) and keeps only
    those whose role list intersects CCAC_ALLOWED_ROLE_IDS.  Result is cached for
    5 minutes so every leaderboard render doesn't hit the Discord API.
    """
    bot_token = get_bot_token()
    if not bot_token:
        return set()
    headers = {"Authorization": f"Bot {bot_token}"}
    usernames: set = set()
    after = 0
    for _ in range(5):  # max 5 pages × 1 000 = 5 000 members
        try:
            members = http_json(
                f"{DISCORD_API_BASE}/guilds/{CCAC_MAIN_GUILD_ID}/members?limit=1000&after={after}",
                headers=headers,
            )
            if not isinstance(members, list) or not members:
                break
            for m in members:
                member_role_ids = {int(r) for r in (m.get("roles") or [])}
                if member_role_ids.intersection(CCAC_ALLOWED_ROLE_IDS):
                    user = m.get("user") or {}
                    un = (user.get("username") or "").strip().lower()
                    if un:
                        usernames.add(un)
            if len(members) < 1000:
                break
            after = int(members[-1]["user"]["id"])
        except Exception:
            break
    return usernames


def clear_auth_query_params():
    try:
        st.query_params.clear()
    except Exception:
        pass


def ensure_discord_auth() -> Dict[str, Any]:
    if "discord_auth" not in st.session_state:
        st.session_state.discord_auth = None

    settings = get_discord_oauth_settings()
    missing = [
        key
        for key, value in (
            ("DISCORD_CLIENT_ID", settings["client_id"]),
            ("DISCORD_CLIENT_SECRET", settings["client_secret"]),
            ("DISCORD_REDIRECT_URI", settings["redirect_uri"]),
        )
        if not value
    ]
    if missing:
        st.error(f"Discord OAuth is not configured. Missing: {', '.join(missing)}")
        st.stop()

    # Restore session from a persistent token in the URL (survives page refresh / new tab).
    raw_session = st.query_params.get("session", "")
    session_token = raw_session[0] if isinstance(raw_session, list) and raw_session else str(raw_session or "")
    if session_token and not st.session_state.discord_auth:
        _prune_session_cache()
        cached = _SESSION_CACHE.get(session_token)
        if cached and cached["expires_at"] > datetime.now(timezone.utc):
            st.session_state.discord_auth = cached["auth"]

    raw_code = st.query_params.get("code", "")
    raw_state = st.query_params.get("state", "")
    code = raw_code[0] if isinstance(raw_code, list) and raw_code else str(raw_code or "")
    state = raw_state[0] if isinstance(raw_state, list) and raw_state else str(raw_state or "")

    if code and not st.session_state.discord_auth:
        try:
            token_payload = exchange_code_for_token(code)
            access_token = token_payload.get("access_token", "")
            if not access_token:
                raise ValueError(token_payload.get("error_description") or "No access token returned by Discord.")

            user = fetch_discord_user(access_token)
            user_id = str(user.get("id", ""))

            if not user_id:
                raise ValueError("Could not retrieve user ID from Discord.")

            role_ids = fetch_member_roles(user_id)

            if not role_ids.intersection(CCAC_ALLOWED_ROLE_IDS):
                raise PermissionError(
                    "Your Discord account does not have the required CCAC staff role "
                    "(Jr. Mod, Mod, Admin, Owner, or Tech), or you are not a member of the server."
                )

            auth_data = {
                "access_token": access_token,
                "user": user,
                "role_ids": list(role_ids),
            }
            st.session_state.discord_auth = auth_data

            # Persist session for 20 minutes via a URL token.
            new_session_token = secrets.token_urlsafe(32)
            _SESSION_CACHE[new_session_token] = {
                "auth": auth_data,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS),
            }
            _prune_session_cache()
            clear_auth_query_params()
            st.query_params["session"] = new_session_token
            st.rerun()
        except Exception as e:
            st.error(f"Discord login failed: {e}")
            st.stop()

    if st.session_state.discord_auth:
        return st.session_state.discord_auth

    # ── Discord login ────────────────────────────────────────────────────────
    st.sidebar.write("🔐 Staff sign-in")
    st.sidebar.caption("Sign in with Discord. Access is limited to members with the required CCAC role.")
    login_state = secrets.token_urlsafe(24)
    st.sidebar.link_button("Sign in with Discord", build_discord_login_url(login_state))

    # ── Advisor password login ───────────────────────────────────────────────
    st.sidebar.divider()
    st.sidebar.write("🎓 Advisor access")
    with st.sidebar.form("advisor_login_form", clear_on_submit=True):
        _pw = st.text_input("Password", type="password", placeholder="Enter advisor password")
        _submitted = st.form_submit_button("Sign in", use_container_width=True)
        if _submitted:
            _entered_hash = hashlib.sha256(_pw.encode()).hexdigest()
            if hmac.compare_digest(_entered_hash, _ADVISOR_PW_HASH):
                _all_role_ids = list(
                    CCAC_ALLOWED_ROLE_IDS | CCAC_ADMIN_ROLE_IDS | CCAC_TECH_ROLE_IDS
                )
                st.session_state.discord_auth = {
                    "access_token": "",
                    "user": {
                        "id": "0",
                        "username": "Thesis Advisor",
                        "global_name": "Thesis Advisor",
                        "discriminator": "0000",
                        "avatar": "",
                    },
                    "role_ids": _all_role_ids,
                    "advisor": True,
                }
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()


def find_dir(candidates: List[str]) -> Path:
    for c in candidates:
        p = Path(c)
        if p.exists() and p.is_dir():
            return p
    return Path(candidates[0])


def load_transcript_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"


def load_transcript_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


MSG_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+(?P<author>[^:]+):\s*(?P<content>.*)$")
IMG_RE = re.compile(r"^\[Image saved:\s*(?P<path>.+)\]$")
ATTACH_RE = re.compile(r"^\[Attachment:\s*(?P<url>.+)\]$")


def parse_transcript(raw: str) -> List[Dict[str, Any]]:
    messages = []
    last = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = MSG_RE.match(line)
        if m:
            last = {
                "ts": m.group("ts"),
                "author": m.group("author").strip(),
                "content": m.group("content").strip(),
                "images": [],
                "attachments": [],
            }
            messages.append(last)
            continue

        m2 = IMG_RE.match(line)
        if m2 and last is not None:
            last["images"].append(m2.group("path").strip())
            continue

        m3 = ATTACH_RE.match(line)
        if m3 and last is not None:
            last["attachments"].append(m3.group("url").strip())
            continue

        if last is not None:
            last["content"] += "\n" + line

    return messages


def is_staff(author: str, staff_identifiers: List[str]) -> bool:
    auth_lower = author.lower()
    for s in staff_identifiers:
        if not s:
            continue
        if s.lower() in auth_lower:
            return True
    return False


def is_internal(content: str, internal_markers: List[str]) -> bool:
    for m in internal_markers:
        if not m:
            continue
        if m.lower() in content.lower():
            return True
    return False


def parse_iso_timestamp(value: str):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def relative_time_label(value: str) -> str:
    ts = parse_iso_timestamp(value)
    if not ts:
        return ""
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    seconds = int(max(delta.total_seconds(), 0))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def inject_transcript_styles():
    st.markdown(
        """
        <style>
        .ticket-summary-card {
            border: 1px solid rgba(192, 16, 64, 0.22);
            border-radius: 12px;
            padding: 16px;
            background: #FFFFFF;
            box-shadow: 0 2px 10px rgba(192, 16, 64, 0.08);
        }
        .ticket-summary-row {
            margin-bottom: 12px;
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(192, 16, 64, 0.10);
        }
        .ticket-summary-row:last-child {
            margin-bottom: 0;
            padding-bottom: 0;
            border-bottom: none;
        }
        .ticket-summary-label {
            font-size: 0.9rem;
            color: #8B0A2A;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .ticket-summary-value {
            margin-top: 4px;
            color: #2D0A14;
        }
        .msg-card {
            border-left: 3px solid rgba(192, 16, 64, 0.55);
            border-radius: 8px;
            padding: 10px 12px;
            margin: 8px 0 14px;
            background: rgba(245, 216, 222, 0.35);
        }
        .msg-system {
            border-left-color: #D86080;
            background: rgba(216, 96, 128, 0.10);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def infer_closed_by(messages: List[Dict[str, Any]], staff_identifiers: List[str]) -> str:
    for msg in reversed(messages):
        role = str(msg.get("role", "")).lower()
        author = msg.get("author", "Unknown")
        if role == "staff" or is_staff(author, staff_identifiers):
            return author
    return "Unknown"


def render_ticket_summary_panel(ticket: Dict[str, Any], messages: List[Dict[str, Any]], staff_identifiers: List[str]):
    server_name = ticket.get("guild_name") or "Unknown"
    owner_name = ticket.get("owner_name") or "Unknown"
    closed_by_name = ticket.get("closed_by") or infer_closed_by(messages, staff_identifiers)
    closed_by_id = ticket.get("closed_by_id") or ticket.get("closed_by_user_id") or ""
    closed_by_display = f"{closed_by_name} | {closed_by_id}" if closed_by_id else closed_by_name
    members_value = f"{owner_name}, {closed_by_name}" if closed_by_name != owner_name else owner_name
    closed_at = ticket.get("closed_at")
    closed_date = ""
    if closed_at:
        try:
            dt = parse_iso_timestamp(closed_at)
            if dt:
                closed_date = dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    # Prefer human-readable category name, fall back to numeric category_id
    category_display = str(ticket.get("category") or ticket.get("category_id") or "—")

    st.markdown(
        f"""
        <div class="ticket-summary-card">
            <div class="ticket-summary-row">
                <div class="ticket-summary-label">Server name</div>
                <div class="ticket-summary-value">{server_name}</div>
            </div>
            <div class="ticket-summary-row">
                <div class="ticket-summary-label">Members</div>
                <div class="ticket-summary-value">{members_value}</div>
            </div>
            <div class="ticket-summary-row">
                <div class="ticket-summary-label">Category</div>
                <div class="ticket-summary-value">{category_display}</div>
            </div>
            <div class="ticket-summary-row">
                <div class="ticket-summary-label">Messages</div>
                <div class="ticket-summary-value">{len(messages)}</div>
            </div>
            <div class="ticket-summary-row">
                <div class="ticket-summary-label">Closed by</div>
                <div class="ticket-summary-value">{closed_by_display}</div>
            </div>
            <div class="ticket-summary-row">
                <div class="ticket-summary-label">Closed date</div>
                <div class="ticket-summary-value">{closed_date}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def normalize_display_message(msg: Dict[str, Any]):
    author = str(msg.get("author", "Unknown") or "Unknown")
    content = str(msg.get("content", "") or "")

    lines = [line for line in content.splitlines()]
    cleaned_lines = []
    prefix = author.strip().lower()
    for idx, line in enumerate(lines):
        lstripped = line.lstrip()
        # Remove any line that starts with 'STAFF RESPONSE:' (case-insensitive, with or without colon)
        if lstripped.lower().startswith("staff response"):
            continue
        # Remove 'user message' marker and possible username on next line
        if idx == 0 and lstripped.lower() == "user message":
            continue
        # Remove username prefix from every line if present (robust: ignore case, allow colon, dash, pipe, period, whitespace)
        lstripped_lower = lstripped.lower()
        for sep in [":", "-", "|", ".", " "]:
            if lstripped_lower.startswith(prefix + sep):
                after = lstripped[len(prefix + sep):].lstrip()
                if after:
                    cleaned_lines.append(after)
                break
        else:
            # Also handle exact match (username only)
            if lstripped_lower == prefix:
                continue
            cleaned_lines.append(line)
    normalized_content = "\n".join(cleaned_lines).strip()
    return author, normalized_content


def is_staff_response_message(msg: Dict[str, Any], normalized_content: str) -> bool:
    raw_content = str(msg.get("content", "") or "")
    raw_lower = raw_content.lower()
    normalized_lower = (normalized_content or "").lower()

    if raw_lower.startswith("%r ") or raw_lower == "%r":
        return True
    if "staff response" in raw_lower or normalized_lower.startswith("staff response"):
        return True

    embeds = msg.get("embeds", [])
    if isinstance(embeds, list):
        for embed in embeds:
            if not isinstance(embed, dict):
                continue
            title = str(embed.get("title", "") or "").lower()
            author = str(embed.get("author", "") or "").lower()
            description = str(embed.get("description", "") or "").lower()
            if "staff response" in title or "staff response" in author or "staff response" in description:
                return True

    return False


def message_is_internal(msg: Dict[str, Any], normalized_content: str, internal_markers: List[str]) -> bool:
    role = str(msg.get("role", "")).lower()
    raw_content = str(msg.get("content", "") or "")
    raw_lower = raw_content.lower()
    trimmed = normalized_content.lstrip()

    if is_internal(normalized_content, internal_markers):
        return True
    if role == "system":
        return True
    if role == "staff":
        return not is_staff_response_message(msg, normalized_content)
    if trimmed.startswith("%") or trimmed.startswith("!") or trimmed.startswith("/"):
        return True
    return False


def get_avatar_url(msg: Dict[str, Any], author: str) -> str:
    avatar_url = str(msg.get("author_avatar_url", "") or "").strip()
    if avatar_url:
        return avatar_url

    author_id = msg.get("author_id")
    if author_id:
        return f"https://unavatar.io/discord/{author_id}"

    return f"https://api.dicebear.com/8.x/initials/svg?seed={quote(author or 'user')}"


def render_messages_appy_style(messages: List[Dict[str, Any]], image_root: Path, staff_identifiers: List[str], show_internal: bool, internal_markers: List[str]):
    prev_author = None
    for idx, msg in enumerate(messages):
        author, content = normalize_display_message(msg)
        internal = message_is_internal(msg, content, internal_markers)
        if internal and not show_internal:
            continue

        role = str(msg.get("role", "")).lower()
        is_system = role == "system"
        is_staff_msg = (role == "staff") or is_staff_response_message(msg, content) or is_staff(author, staff_identifiers)
        avatar_url = get_avatar_url(msg, author)

        # Add extra vertical space if author changes
        extra_top_margin = 28 if prev_author is not None and author != prev_author else 8
        prev_author = author

        # Minimal, modern bubble style
        if is_staff_msg:
            bubble_style = "background:#7B0020;border-radius:10px;padding:13px 18px 13px 16px;box-shadow:0 2px 8px rgba(192,16,64,0.18);color:#FBF0F2;"
        else:
            bubble_style = "background:#FFFFFF;border:1px solid rgba(192,16,64,0.18);border-radius:10px;padding:13px 18px 13px 16px;box-shadow:0 2px 6px rgba(192,16,64,0.07);color:#2D0A14;"

        # Use a single column and flexbox for Discord-like alignment
        with st.container():
            if is_staff_msg:
                st.markdown(f'''
                <div style="display: flex; flex-direction: row; justify-content: flex-end; align-items: flex-start; margin-bottom: 18px;">
                    <div style="display: flex; flex-direction: column; align-items: flex-end;">
                        <div style='text-align:right;margin-bottom:2px;'><strong>{author}</strong> <span style='background:#C01040;color:#fff;border-radius:6px;padding:2px 8px;font-size:0.85em;margin-left:8px;'>Staff</span></div>
                        <div style='{bubble_style}margin-bottom:2px;min-width:60px;display:inline-block;text-align:left;'>
                            {(content or '').replace(chr(10), '<br>')}
                        </div>
                    </div>
                    <img src="{avatar_url}" width="44" style="border-radius:8px;margin-left:12px;object-fit:cover;" />
                </div>
                ''', unsafe_allow_html=True)
                # Embeds, images, attachments for staff
                embeds = msg.get("embeds", [])
                if not content and isinstance(embeds, list):
                    for embed in embeds:
                        pass
                for img_path in msg.get("images", []):
                    p = Path(img_path)
                    if not p.exists():
                        p = image_root.joinpath(Path(img_path).name)
                    if p.exists():
                        try:
                            st.image(Image.open(p), use_column_width=True)
                        except Exception as e:
                            st.write(f"[Image could not be opened: {p} ({e})]")
                    else:
                        st.write(f"[Image not found: {img_path}]")
                for url in msg.get("attachments", []):
                    st.write(f"[Attachment: {url}]")
            else:
                st.markdown(f'''
                <div style="display: flex; flex-direction: row; justify-content: flex-start; align-items: flex-start; margin-bottom: 18px;">
                    <img src="{avatar_url}" width="44" style="border-radius:8px;margin-right:12px;object-fit:cover;" />
                    <div style="display: flex; flex-direction: column; align-items: flex-start;">
                        <div style='margin-bottom:2px;'><strong>{author}</strong> <span style='background:#D86080;color:#fff;border-radius:6px;padding:2px 8px;font-size:0.85em;margin-left:8px;'>User</span></div>
                        <div style='{bubble_style}margin-bottom:2px;min-width:60px;display:inline-block;'>
                            {(content or '').replace(chr(10), '<br>')}
                        </div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
                # Embeds, images, attachments for user
                embeds = msg.get("embeds", [])
                if not content and isinstance(embeds, list):
                    for embed in embeds:
                        pass
                for img_path in msg.get("images", []):
                    p = Path(img_path)
                    if not p.exists():
                        p = image_root.joinpath(Path(img_path).name)
                    if p.exists():
                        try:
                            st.image(Image.open(p), use_column_width=True)
                        except Exception as e:
                            st.write(f"[Image could not be opened: {p} ({e})]")
                    else:
                        st.write(f"[Image not found: {img_path}]")
                for url in msg.get("attachments", []):
                    st.write(f"[Attachment: {url}]")



def render_messages(messages: List[Dict[str, Any]], image_root: Path, staff_identifiers: List[str], show_internal: bool, internal_markers: List[str]):
    for msg in messages:
        internal = is_internal(msg.get("content", ""), internal_markers)
        if internal and not show_internal:
            continue

        role = str(msg.get("role", "")).lower()
        staff = role == "staff" or is_staff(msg.get("author", ""), staff_identifiers)
        bubble_role = "assistant" if staff else "user"
        ts = msg.get("ts") or msg.get("timestamp") or ""

        with st.chat_message(bubble_role):
            st.markdown(f"**{msg.get('author', '')}**  ")
            if ts:
                st.caption(ts)
            st.write(msg.get("content", ""))

            embeds = msg.get("embeds", [])
            if isinstance(embeds, list):
                for embed in embeds:
                    if not isinstance(embed, dict):
                        continue
                    embed_title = embed.get("title", "")
                    embed_author = embed.get("author", "")
                    embed_description = embed.get("description", "")
                    embed_fields = embed.get("fields", [])

                    if embed_title:
                        st.markdown(f"**Embed:** {embed_title}")
                    if embed_author:
                        st.caption(f"Embed author: {embed_author}")
                    if embed_description:
                        st.write(embed_description)

                    if isinstance(embed_fields, list) and embed_fields:
                        for field in embed_fields:
                            if not isinstance(field, dict):
                                continue
                            field_name = field.get("name", "")
                            field_value = field.get("value", "")
                            if field_name and field_value:
                                st.markdown(f"**{field_name}**")
                                st.write(field_value)
                            elif field_value:
                                st.write(field_value)

            for img_path in msg.get("images", []):
                p = Path(img_path)
                if not p.exists():
                    p = image_root.joinpath(Path(img_path).name)
                if p.exists():
                    try:
                        st.image(Image.open(p), use_column_width=True)
                    except Exception as e:
                        st.write(f"[Image could not be opened: {p} ({e})]")
                else:
                    st.write(f"[Image not found: {img_path}]")

            for url in msg.get("attachments", []):
                st.markdown(f"Attachment: [{url}]({url})")


def query_mysql_tickets():
    """Query active_tickets from MySQL database."""
    if not MYSQL_AVAILABLE:
        st.error("mysql-connector-python not installed. Install: pip install mysql-connector-python")
        return None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT channel_id, user_id, member_username, mod_username, category_id, created_at, closed_at, status FROM active_tickets ORDER BY created_at DESC LIMIT 500"
        )
        tickets = cursor.fetchall()
        cursor.close()
        conn.close()
        return tickets
    except Error as e:
        st.error(f"Database error: {e}")
    except Exception as e:
        st.error(f"Connection error: {e}")
    return None


def query_exact_ticket_counts() -> Dict[str, int]:
    """Return exact open/closed ticket counts directly from the DB (no LIMIT)."""
    if not MYSQL_AVAILABLE:
        return {"open": 0, "closed": 0}
    try:
        conn = _new_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                SUM(status = 'open')   AS open_count,
                SUM(status = 'closed') AS closed_count
            FROM active_tickets
            """
        )
        row = cursor.fetchone() or {}
        cursor.close()
        conn.close()
        return {
            "open":   int(row.get("open_count") or 0),
            "closed": int(row.get("closed_count") or 0),
        }
    except Exception:
        return {"open": 0, "closed": 0}


def query_mysql_transcripts_map() -> Dict[str, Dict[str, Any]]:
    """Return map[channel_id] => transcript JSON payload from ticket_transcripts table."""
    if not MYSQL_AVAILABLE:
        return {}

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT channel_id, owner_id, owner_name, opened_by, closed_by, opened_at, closed_at, transcript_json
            FROM ticket_transcripts
            ORDER BY updated_at DESC
            LIMIT 2000
            """
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            channel_id = str(row.get("channel_id"))
            payload = row.get("transcript_json")
            if not channel_id or not isinstance(payload, str):
                continue
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    ticket = parsed.setdefault("ticket", {})
                    if isinstance(ticket, dict):
                        ticket.setdefault("owner_id", row.get("owner_id"))
                        ticket.setdefault("owner_name", row.get("owner_name"))
                        ticket.setdefault("opened_by", row.get("opened_by"))
                        ticket.setdefault("closed_by", row.get("closed_by"))
                        ticket.setdefault("opened_at", row.get("opened_at"))
                        ticket.setdefault("closed_at", row.get("closed_at"))
                    result[channel_id] = parsed
            except Exception:
                continue
        return result
    except Exception:
        return {}


# ── Premade messages (dx_responses) DB helpers ───────────────────────────────

def query_dx_responses() -> List[Dict[str, str]]:
    """Return all premade messages as [{'key': ..., 'response': ...}]."""
    if not MYSQL_AVAILABLE:
        return []
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT `key`, `response` FROM dx_responses ORDER BY `key` ASC")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [{"key": r["key"], "response": r["response"]} for r in rows]
    except Exception:
        return []


def upsert_dx_response(key: str, response: str) -> None:
    """Insert or update a premade message by key."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO dx_responses (`key`, `response`) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE `response` = VALUES(`response`)",
        (key, response),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_dx_response(key: str) -> None:
    """Delete a premade message by key."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM dx_responses WHERE `key` = %s", (key,))
    conn.commit()
    cursor.close()
    conn.close()


# ── Shared connection helper ──────────────────────────────────────────────────

def _new_conn():
    """Return a fresh mysql.connector connection using DB_CONFIG."""
    return mysql.connector.connect(**DB_CONFIG)


# ── Table bootstrap ───────────────────────────────────────────────────────────

def _ensure_table(ddl: str) -> None:
    """Run a CREATE TABLE IF NOT EXISTS statement, silently ignoring errors."""
    if not MYSQL_AVAILABLE:
        return
    try:
        conn = _new_conn()
        cursor = conn.cursor()
        cursor.execute(ddl)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass


def ensure_admin_log_table() -> None:
    _ensure_table(
        """
        CREATE TABLE IF NOT EXISTS admin_action_log (
            id           BIGINT AUTO_INCREMENT PRIMARY KEY,
            performed_by VARCHAR(255),
            action_type  VARCHAR(100),
            details      TEXT,
            performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def ensure_flagged_users_table() -> None:
    _ensure_table(
        """
        CREATE TABLE IF NOT EXISTS flagged_users (
            user_id    BIGINT PRIMARY KEY,
            username   VARCHAR(255),
            flag_type  VARCHAR(50) DEFAULT 'flagged',
            reason     TEXT,
            flagged_by VARCHAR(255),
            flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def ensure_category_names_table() -> None:
    _ensure_table(
        """
        CREATE TABLE IF NOT EXISTS ticket_category_names (
            category_id   BIGINT PRIMARY KEY,
            category_name VARCHAR(255) NOT NULL,
            updated_by    VARCHAR(255),
            updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """
    )


def ensure_bot_config_table() -> None:
    _ensure_table(
        """
        CREATE TABLE IF NOT EXISTS bot_config_overrides (
            `key`       VARCHAR(100) PRIMARY KEY,
            `value`     TEXT,
            updated_by  VARCHAR(255),
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """
    )


# ── Admin action log ──────────────────────────────────────────────────────────

def log_admin_action(performed_by: str, action_type: str, details: str) -> None:
    """Record an admin action in admin_action_log. Never raises."""
    if not MYSQL_AVAILABLE:
        return
    try:
        ensure_admin_log_table()
        conn = _new_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO admin_action_log (performed_by, action_type, details) VALUES (%s, %s, %s)",
            (performed_by, action_type, details),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass


def query_admin_action_log(limit: int = 100) -> List[Dict[str, Any]]:
    if not MYSQL_AVAILABLE:
        return []
    try:
        ensure_admin_log_table()
        conn = _new_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, performed_by, action_type, details, performed_at "
            "FROM admin_action_log ORDER BY performed_at DESC LIMIT %s",
            (limit,),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception:
        return []


# ── Stats queries ─────────────────────────────────────────────────────────────

def query_ticket_stats() -> Dict[str, Any]:
    """Return aggregated counts from active_tickets."""
    if not MYSQL_AVAILABLE:
        return {}
    try:
        conn = _new_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT status, COUNT(*) AS cnt FROM active_tickets GROUP BY status")
        by_status: Dict[str, int] = {r["status"]: r["cnt"] for r in cursor.fetchall()}
        cursor.execute(
            "SELECT category_id, COUNT(*) AS cnt FROM active_tickets "
            "GROUP BY category_id ORDER BY cnt DESC"
        )
        by_category: List[Dict[str, Any]] = cursor.fetchall()
        cursor.execute(
            """
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt
            FROM active_tickets
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY DATE(created_at)
            ORDER BY day
            """
        )
        daily_opens: List[Dict[str, Any]] = cursor.fetchall()
        cursor.execute(
            """
            SELECT AVG(TIMESTAMPDIFF(MINUTE, created_at, closed_at)) AS avg_mins
            FROM active_tickets
            WHERE status = 'closed'
              AND closed_at IS NOT NULL
              AND created_at IS NOT NULL
            """
        )
        row = cursor.fetchone()
        avg_mins = row["avg_mins"] if row and row["avg_mins"] is not None else None
        cursor.close()
        conn.close()
        return {
            "by_status": by_status,
            "by_category": by_category,
            "daily_opens": daily_opens,
            "avg_resolution_hours": round(avg_mins / 60, 1) if avg_mins is not None else None,
        }
    except Exception:
        return {}


def query_staff_leaderboard() -> List[Dict[str, Any]]:
    """Return staff ticket close counts, sorted descending."""
    if not MYSQL_AVAILABLE:
        return []
    try:
        conn = _new_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT mod_username, COUNT(*) AS closed_count
            FROM active_tickets
            WHERE status = 'closed'
              AND mod_username IS NOT NULL
              AND mod_username != ''
            GROUP BY mod_username
            ORDER BY closed_count DESC
            LIMIT 25
            """
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception:
        return []


def query_open_tickets_with_age() -> List[Dict[str, Any]]:
    """Return open tickets enriched with age_hours since creation."""
    if not MYSQL_AVAILABLE:
        return []
    try:
        conn = _new_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT channel_id, user_id, member_username, mod_username,
                   category_id, created_at,
                   TIMESTAMPDIFF(HOUR, created_at, NOW()) AS age_hours
            FROM active_tickets
            WHERE status = 'open'
            ORDER BY created_at ASC
            """
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception:
        return []


# ── User search ───────────────────────────────────────────────────────────────

def query_user_tickets(search_term: str) -> List[Dict[str, Any]]:
    """Return tickets matching a username or user ID."""
    if not MYSQL_AVAILABLE or not search_term.strip():
        return []
    try:
        conn = _new_conn()
        cursor = conn.cursor(dictionary=True)
        like_term = f"%{search_term.strip()}%"
        try:
            uid = int(search_term.strip())
            cursor.execute(
                """
                SELECT channel_id, user_id, member_username, mod_username,
                       category_id, created_at, closed_at, status
                FROM active_tickets
                WHERE user_id = %s OR member_username LIKE %s
                ORDER BY created_at DESC LIMIT 100
                """,
                (uid, like_term),
            )
        except ValueError:
            cursor.execute(
                """
                SELECT channel_id, user_id, member_username, mod_username,
                       category_id, created_at, closed_at, status
                FROM active_tickets
                WHERE member_username LIKE %s
                ORDER BY created_at DESC LIMIT 100
                """,
                (like_term,),
            )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception:
        return []


# ── Flagged users ─────────────────────────────────────────────────────────────

def query_flagged_users() -> List[Dict[str, Any]]:
    if not MYSQL_AVAILABLE:
        return []
    try:
        ensure_flagged_users_table()
        conn = _new_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, username, flag_type, reason, flagged_by, flagged_at "
            "FROM flagged_users ORDER BY flagged_at DESC"
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception:
        return []


def upsert_flagged_user(
    user_id: int, username: str, flag_type: str, reason: str, flagged_by: str
) -> None:
    ensure_flagged_users_table()
    conn = _new_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO flagged_users (user_id, username, flag_type, reason, flagged_by, flagged_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            username   = VALUES(username),
            flag_type  = VALUES(flag_type),
            reason     = VALUES(reason),
            flagged_by = VALUES(flagged_by),
            flagged_at = NOW()
        """,
        (user_id, username, flag_type, reason, flagged_by),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_flagged_user(user_id: int) -> None:
    conn = _new_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM flagged_users WHERE user_id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()


# ── Category names ────────────────────────────────────────────────────────────

def query_category_names() -> Dict[int, str]:
    """Return {category_id: friendly_name} saved by admins."""
    if not MYSQL_AVAILABLE:
        return {}
    try:
        ensure_category_names_table()
        conn = _new_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT category_id, category_name FROM ticket_category_names")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return {r["category_id"]: r["category_name"] for r in rows}
    except Exception:
        return {}


def upsert_category_name(category_id: int, category_name: str, updated_by: str) -> None:
    ensure_category_names_table()
    conn = _new_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO ticket_category_names (category_id, category_name, updated_by)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            category_name = VALUES(category_name),
            updated_by    = VALUES(updated_by)
        """,
        (category_id, category_name, updated_by),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_category_name(category_id: int) -> None:
    conn = _new_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ticket_category_names WHERE category_id = %s", (category_id,))
    conn.commit()
    cursor.close()
    conn.close()


def query_distinct_category_ids() -> List[int]:
    """Return all distinct category_ids in active_tickets."""
    if not MYSQL_AVAILABLE:
        return []
    try:
        conn = _new_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT category_id FROM active_tickets "
            "WHERE category_id IS NOT NULL ORDER BY category_id"
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


# ── Bot config overrides ──────────────────────────────────────────────────────

def query_bot_config_overrides() -> Dict[str, str]:
    if not MYSQL_AVAILABLE:
        return {}
    try:
        ensure_bot_config_table()
        conn = _new_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT `key`, `value` FROM bot_config_overrides ORDER BY `key`")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


def upsert_bot_config(key: str, value: str, updated_by: str) -> None:
    ensure_bot_config_table()
    conn = _new_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO bot_config_overrides (`key`, `value`, updated_by)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            `value`    = VALUES(`value`),
            updated_by = VALUES(updated_by)
        """,
        (key, value, updated_by),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_bot_config(key: str) -> None:
    conn = _new_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bot_config_overrides WHERE `key` = %s", (key,))
    conn.commit()
    cursor.close()
    conn.close()


# ── DixieModerator DB (PyMySQL) ───────────────────────────────────────────────

def _get_dixie_conn():
    """Return a PyMySQL connection to the DixieModerator database."""
    if not PYMYSQL_AVAILABLE:
        raise RuntimeError("pymysql is not installed. Run: pip install pymysql")
    return pymysql.connect(
        host=DIXIE_DB_CONFIG["host"],
        port=DIXIE_DB_CONFIG["port"],
        user=DIXIE_DB_CONFIG["user"],
        password=DIXIE_DB_CONFIG["password"],
        database=DIXIE_DB_CONFIG["database"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


def query_dixie_blacklist() -> List[Dict[str, Any]]:
    """Return all rows from the DixieModerator blacklist table, newest first."""
    try:
        conn = _get_dixie_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, username, reason, blacklist_date "
                "FROM blacklist ORDER BY blacklist_date DESC"
            )
            rows = cur.fetchall()
        conn.close()
        return list(rows)
    except Exception as exc:
        st.error(f"Blacklist DB error: {exc}")
        return []


def list_transcript_files(transcript_dir: Path) -> Dict[str, Path]:
    if not transcript_dir.exists():
        return {}
    mapping = {}
    for p in transcript_dir.glob("*.json"):
        channel_id = p.stem
        if channel_id.isdigit():
            mapping[channel_id] = p
    for p in transcript_dir.glob("*.txt"):
        channel_id = p.stem
        if channel_id.isdigit() and channel_id not in mapping:
            mapping[channel_id] = p
    return mapping


def normalize_query_value(value: Any) -> str:
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def canonical_staff_names(user: Dict[str, Any]) -> List[str]:
    values = [
        str(user.get("username", "") or ""),
        str(user.get("global_name", "") or ""),
    ]
    discriminator = str(user.get("discriminator", "") or "")
    username = str(user.get("username", "") or "")
    if username and discriminator and discriminator != "0":
        values.append(f"{username}#{discriminator}")
    return [value.strip() for value in values if value and value.strip()]


def name_matches_staff(name: Any, possible_names: List[str]) -> bool:
    normalized = str(name or "").strip().lower()
    if not normalized:
        return False
    for candidate in possible_names:
        cand = candidate.strip().lower()
        if not cand:
            continue
        if normalized == cand or normalized.startswith(f"{cand}#") or cand in normalized:
            return True
    return False


def classify_message_kind(msg: Dict[str, Any], normalized_content: str, internal_markers: List[str], staff_identifiers: List[str]) -> str:
    if message_is_internal(msg, normalized_content, internal_markers):
        return "internal"

    role = str(msg.get("role", "")).lower()
    if role == "user":
        return "user"
    if role == "staff" or is_staff_response_message(msg, normalized_content) or is_staff(str(msg.get("author", "")), staff_identifiers):
        return "staff"
    return "internal"


def filter_messages_by_kind(messages: List[Dict[str, Any]], internal_markers: List[str], staff_identifiers: List[str], allowed_kinds: set) -> List[Dict[str, Any]]:
    filtered = []
    for msg in messages:
        _author, content = normalize_display_message(msg)
        if classify_message_kind(msg, content, internal_markers, staff_identifiers) in allowed_kinds:
            filtered.append(msg)
    return filtered


def compute_staff_overview_metrics(tickets: List[Dict[str, Any]], db_transcripts_map: Dict[str, Dict[str, Any]], discord_auth: Dict[str, Any]) -> Dict[str, int]:
    user = discord_auth.get("user", {})
    user_id = int(user.get("id", 0) or 0)
    possible_names = canonical_staff_names(user)

    assigned_open = 0
    assigned_closed = 0
    closed_by_staff = 0
    staff_replies = 0
    handled_channels = set()

    for ticket in tickets:
        mod_username = ticket.get("mod_username")
        if name_matches_staff(mod_username, possible_names):
            if str(ticket.get("status", "")).lower() == "open":
                assigned_open += 1
            else:
                assigned_closed += 1

    for channel_id, transcript_payload in db_transcripts_map.items():
        if not isinstance(transcript_payload, dict):
            continue
        ticket = transcript_payload.get("ticket", {}) if isinstance(transcript_payload.get("ticket", {}), dict) else {}
        messages = transcript_payload.get("messages", []) if isinstance(transcript_payload.get("messages", []), list) else []

        closed_by = ticket.get("closed_by") or transcript_payload.get("closed_by")
        if name_matches_staff(closed_by, possible_names):
            closed_by_staff += 1
            handled_channels.add(channel_id)

        for msg in messages:
            author_id = int(msg.get("author_id", 0) or 0)
            author_name = str(msg.get("author", "") or "")
            role = str(msg.get("role", "")).lower()
            if role == "staff" and (author_id == user_id or name_matches_staff(author_name, possible_names)):
                staff_replies += 1
                handled_channels.add(channel_id)

    return {
        "assigned_open": assigned_open,
        "assigned_closed": assigned_closed,
        "closed_by_you": closed_by_staff,
        "staff_replies": staff_replies,
        "handled_tickets": len(handled_channels),
    }


def render_premade_messages_section() -> None:
    """Admin-only section: view, add, edit, and delete premade responses (dx_responses)."""
    st.subheader("Premade Messages")
    st.caption("Changes here take effect immediately in the Discord bot (`%key` shortcuts).")

    if not MYSQL_AVAILABLE:
        st.error("mysql-connector-python is not installed.")
        return

    discord_auth = st.session_state.get("discord_auth") or {}
    me = (discord_auth.get("user") or {}).get("username") or "unknown"

    # ── Load ─────────────────────────────────────────────────────────────────
    try:
        responses = query_dx_responses()
    except Exception as e:
        st.error(f"Could not load premade messages: {e}")
        return

    # ── Add new message ───────────────────────────────────────────────────────
    with st.expander("Add new premade message", expanded=not responses):
        new_key = st.text_input(
            "Key (used as `%key` in Discord)",
            placeholder="e.g. rules",
            key="pm_new_key",
        ).strip().lower()
        new_body = st.text_area(
            "Message body",
            placeholder="Type the full message text here…",
            key="pm_new_body",
            height=120,
        ).strip()
        if st.button("Save new message", key="pm_add_btn", type="primary"):
            if not new_key:
                st.warning("Key cannot be empty.")
            elif not new_body:
                st.warning("Message body cannot be empty.")
            elif any(r["key"] == new_key for r in responses):
                st.warning(f"Key `{new_key}` already exists — edit it in the table below.")
            else:
                try:
                    upsert_dx_response(new_key, new_body)
                    log_admin_action(me, "premade_add", f"key={new_key}")
                    st.success(f"Premade message `{new_key}` saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save: {e}")

    st.divider()

    # ── Edit / delete existing ────────────────────────────────────────────────
    if not responses:
        st.info("No premade messages yet.")
        return

    st.markdown(f"**{len(responses)} premade message{'s' if len(responses) != 1 else ''}**")

    for idx, row in enumerate(responses):
        key = row["key"]
        with st.expander(f"`%{key}`", expanded=False):
            edited_key = st.text_input(
                "Key",
                value=key,
                key=f"pm_key_{idx}",
            ).strip().lower()
            edited_body = st.text_area(
                "Message body",
                value=row["response"],
                key=f"pm_body_{idx}",
                height=140,
            ).strip()

            col_save, col_del, _ = st.columns([1, 1, 3])

            with col_save:
                if st.button("Save changes", key=f"pm_save_{idx}", type="primary"):
                    if not edited_key:
                        st.warning("Key cannot be empty.")
                    elif not edited_body:
                        st.warning("Message body cannot be empty.")
                    else:
                        try:
                            if edited_key != key:
                                # Key renamed: delete old, insert new
                                delete_dx_response(key)
                            upsert_dx_response(edited_key, edited_body)
                            log_admin_action(me, "premade_edit", f"key={edited_key}")
                            st.success(f"Saved `{edited_key}`.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to save: {e}")

            with col_del:
                if st.button("Delete", key=f"pm_del_{idx}"):
                    try:
                        delete_dx_response(key)
                        log_admin_action(me, "premade_delete", f"key={key}")
                        st.success(f"Deleted `{key}`.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to delete: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Admin dashboard sections (all require is_admin; config editor requires is_tech)
# ══════════════════════════════════════════════════════════════════════════════

# ─── 1. Stats Dashboard ───────────────────────────────────────────────────────

def render_stats_dashboard() -> None:
    st.subheader("Stats Dashboard")

    if not MYSQL_AVAILABLE:
        st.error("MySQL not available.")
        return

    with st.spinner("Loading stats…"):
        stats = query_ticket_stats()

    if not stats:
        st.warning("Could not load stats from the database.")
        return

    by_status = stats.get("by_status", {})
    open_c    = by_status.get("open", 0)
    closed_c  = by_status.get("closed", 0)
    total     = open_c + closed_c
    avg_h     = stats.get("avg_resolution_hours")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Tickets",   total)
    c2.metric("Open",            open_c)
    c3.metric("Closed",          closed_c)
    c4.metric("Avg Resolution",  f"{avg_h}h" if avg_h is not None else "—")

    st.divider()

    # Tickets by category
    by_cat = stats.get("by_category", [])
    if by_cat:
        st.markdown("**Tickets by category**")
        cat_names_db = query_category_names()
        config_cat_map: Dict[int, str] = {}
        if app_config:
            try:
                config_cat_map = {v: k for k, v in getattr(app_config, "CATEGORY_IDS", {}).items()}
            except Exception:
                pass
        max_cnt = max((r["cnt"] for r in by_cat), default=1)
        for row in by_cat[:20]:
            cat_id   = row["category_id"] or 0
            cat_name = cat_names_db.get(cat_id) or config_cat_map.get(cat_id) or str(cat_id)
            st.progress(
                min(row["cnt"] / max_cnt, 1.0),
                text=f"**{cat_name}** — {row['cnt']} ticket{'s' if row['cnt'] != 1 else ''}",
            )

    st.divider()

    # Daily ticket opens (last 30 days)
    daily = stats.get("daily_opens", [])
    if daily:
        st.markdown("**Ticket opens — last 30 days**")
        try:
            import pandas as pd
            df = pd.DataFrame(daily)
            df["day"] = df["day"].astype(str)
            df = df.set_index("day").rename(columns={"cnt": "Opens"})
            st.bar_chart(df)
        except Exception:
            st.bar_chart({str(r["day"]): r["cnt"] for r in daily})
    else:
        st.info("No ticket data in the last 30 days.")


# ─── 2. Staff Activity Leaderboard ───────────────────────────────────────────

def render_staff_leaderboard() -> None:
    st.subheader("Staff Activity Leaderboard")
    st.caption("Only staff who currently hold a staff role in the Discord server are shown.")

    if not MYSQL_AVAILABLE:
        st.error("MySQL not available.")
        return

    col_ref, _ = st.columns([1, 4])
    with col_ref:
        if st.button("↺ Refresh staff list", key="lb_refresh_staff"):
            fetch_current_staff_usernames.clear()
            st.rerun()

    with st.spinner("Loading leaderboard…"):
        rows = query_staff_leaderboard()
        current_staff = fetch_current_staff_usernames()

    # Filter to only staff who are currently in the server with a staff role.
    # If the Discord API is unreachable (empty set returned), fall back to showing all.
    if current_staff:
        rows = [r for r in rows if (r.get("mod_username") or "").strip().lower() in current_staff]

    if not rows:
        st.info("No closed tickets found for current staff members.")
        return

    medals = ["🥇", "🥈", "🥉"]
    st.markdown(f"**Top {len(rows)} active staff members by tickets closed**")
    max_c = rows[0]["closed_count"] or 1
    for i, row in enumerate(rows):
        prefix = medals[i] if i < 3 else f"**#{i + 1}**"
        name   = row["mod_username"] or "Unknown"
        count  = row["closed_count"]
        st.progress(count / max_c, text=f"{prefix} {name} — {count} closed")

    st.divider()
    try:
        import pandas as pd
        df = pd.DataFrame(rows).rename(
            columns={"mod_username": "Staff", "closed_count": "Tickets Closed"}
        ).set_index("Staff")
        st.bar_chart(df["Tickets Closed"])
    except Exception:
        st.table(rows)


# ─── 3. Open Ticket Monitor ───────────────────────────────────────────────────

def render_open_tickets_monitor() -> None:
    st.subheader("Open Ticket Monitor")

    if not MYSQL_AVAILABLE:
        st.error("MySQL not available.")
        return

    with st.spinner("Loading open tickets…"):
        tickets = query_open_tickets_with_age()

    if not tickets:
        st.success("No open tickets right now.")
        return

    st.metric("Currently open", len(tickets))
    stale = [t for t in tickets if (t.get("age_hours") or 0) >= 48]
    if stale:
        st.warning(
            f"{len(stale)} ticket{'s' if len(stale) != 1 else ''} stale (≥ 48 h without a response)"
        )

    cat_names_db = query_category_names()
    config_cat_map: Dict[int, str] = {}
    if app_config:
        try:
            config_cat_map = {v: k for k, v in getattr(app_config, "CATEGORY_IDS", {}).items()}
        except Exception:
            pass

    display = []
    for t in tickets:
        cat_id   = t.get("category_id")
        cat_name = cat_names_db.get(cat_id) or config_cat_map.get(cat_id) or str(cat_id or "—")
        age_h    = t.get("age_hours") or 0
        display.append({
            "Channel":  str(t.get("channel_id", "")),
            "User":     t.get("member_username", ""),
            "Mod":      t.get("mod_username") or "Unassigned",
            "Category": cat_name,
            "Age (h)":  age_h,
            "Stale":    "⚠ yes" if age_h >= 48 else "",
        })

    try:
        import pandas as pd
        df = pd.DataFrame(display).sort_values("Age (h)", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception:
        st.table(display)


# ─── 4. Ticket Search by User ─────────────────────────────────────────────────

def render_user_search() -> None:
    st.subheader("Ticket Search by User")
    st.caption("Search by Discord username or numeric user ID.")

    search = st.text_input(
        "Username or User ID",
        placeholder="e.g. moussecake or 123456789012345678",
        key="usr_search_q",
    ).strip()

    if not search:
        return

    if not MYSQL_AVAILABLE:
        st.error("MySQL not available.")
        return

    with st.spinner("Searching…"):
        results = query_user_tickets(search)

    if not results:
        st.info("No tickets found for that user.")
        return

    st.success(f"{len(results)} ticket{'s' if len(results) != 1 else ''} found")

    for t in results:
        channel_id = str(t.get("channel_id", ""))
        member     = t.get("member_username", "—")
        mod        = t.get("mod_username") or "Unassigned"
        status     = t.get("status", "")
        created    = str(t.get("created_at", ""))[:10]
        closed     = str(t.get("closed_at", "") or "")[:10] or "—"
        badge      = "🟢" if status == "open" else "⚫"
        link       = f"?section=logs&channel={quote(channel_id)}"
        st.markdown(
            f"{badge} **#{channel_id}** · user: `{member}` · mod: {mod} "
            f"· created: {created} · closed: {closed}"
        )
        st.link_button("Open Transcript", link, key=f"usrlink_{channel_id}")
        st.divider()


# ─── 5. Banned / Flagged Users ────────────────────────────────────────────────

def render_flagged_users_section() -> None:
    st.subheader("Banned / Flagged Users")

    if not MYSQL_AVAILABLE:
        st.error("MySQL not available.")
        return

    discord_auth = st.session_state.get("discord_auth") or {}
    me = (discord_auth.get("user") or {}).get("username") or "unknown"

    with st.expander("Add / update flag", expanded=False):
        f_uid  = st.text_input("Discord User ID (required)", key="fl_uid").strip()
        f_name = st.text_input("Username (optional)", key="fl_name").strip()
        f_type = st.selectbox("Flag type", ["flagged", "banned", "warn", "watch"], key="fl_type")
        f_rsn  = st.text_area("Reason", key="fl_reason", height=80).strip()
        if st.button("Save flag", key="fl_save_btn", type="primary"):
            if not f_uid.isdigit():
                st.warning("User ID must be a number.")
            else:
                try:
                    upsert_flagged_user(int(f_uid), f_name, f_type, f_rsn, me)
                    log_admin_action(me, "flag_user", f"type={f_type} uid={f_uid} user={f_name}: {f_rsn}")
                    st.success(f"User {f_uid} flagged as {f_type}.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {exc}")

    st.divider()

    with st.spinner("Loading…"):
        flagged = query_flagged_users()

    if not flagged:
        st.info("No flagged users.")
        return

    st.markdown(f"**{len(flagged)} flagged user{'s' if len(flagged) != 1 else ''}**")
    for row in flagged:
        uid    = row.get("user_id")
        uname  = row.get("username") or "—"
        ftype  = row.get("flag_type", "flagged")
        reason = row.get("reason") or "No reason given"
        by_who = row.get("flagged_by") or "—"
        at_dt  = row.get("flagged_at")
        at_str = str(at_dt)[:10] if at_dt else "—"
        badge  = {"banned": "🔴", "flagged": "🟠", "warn": "🟡", "watch": "🔵"}.get(ftype, "⚪")
        with st.expander(f"{badge} `{uid}` · {uname} · {ftype}", expanded=False):
            st.markdown(f"**Reason:** {reason}")
            st.caption(f"Flagged by {by_who} on {at_str}")
            if st.button("Remove flag", key=f"fl_del_{uid}"):
                try:
                    delete_flagged_user(int(uid))
                    log_admin_action(me, "unflag_user", f"uid={uid} user={uname}")
                    st.success(f"Flag removed for {uid}.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {exc}")


# ─── 6a. Blacklist ────────────────────────────────────────────────────────────

def render_blacklist_section() -> None:
    st.subheader("Blacklist")
    st.caption("Read from the DixieModerator database (`s404394_DixieModerator` → `blacklist` table).")

    if not PYMYSQL_AVAILABLE:
        st.error("pymysql is not installed. Run: `pip install pymysql`")
        return

    with st.spinner("Loading blacklist…"):
        rows = query_dixie_blacklist()

    if not rows:
        st.info("No blacklist entries found (or database is unreachable).")
        return

    # Search / filter
    search = st.text_input("Search by username or reason", placeholder="e.g. ToxicUser or 'repeated harassment'")
    if search:
        term = search.lower()
        rows = [
            r for r in rows
            if term in str(r.get("username", "")).lower()
            or term in str(r.get("reason", "")).lower()
            or str(r.get("user_id", "")) == search.strip()
        ]

    st.caption(f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'} shown")

    if not rows:
        st.info("No entries match your search.")
        return

    import pandas as pd
    df = pd.DataFrame(rows, columns=["id", "user_id", "username", "reason", "blacklist_date"])
    df["user_id"] = df["user_id"].astype(str)
    df["blacklist_date"] = pd.to_datetime(df["blacklist_date"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
    df = df.rename(columns={
        "id": "ID",
        "user_id": "User ID",
        "username": "Username",
        "reason": "Reason",
        "blacklist_date": "Blacklisted On",
    })
    st.dataframe(df, use_container_width=True, hide_index=True)


# ─── 6. Category Management ───────────────────────────────────────────────────

def render_category_management() -> None:
    st.subheader("Category Management")
    st.caption("Assign human-readable names to Discord category channel IDs used in tickets.")

    if not MYSQL_AVAILABLE:
        st.error("MySQL not available.")
        return

    discord_auth = st.session_state.get("discord_auth") or {}
    me = (discord_auth.get("user") or {}).get("username") or "unknown"

    # Combine IDs from config.py, DB, and saved overrides
    config_cat_map: Dict[int, str] = {}
    if app_config:
        try:
            config_cat_map = {v: k for k, v in getattr(app_config, "CATEGORY_IDS", {}).items()}
        except Exception:
            pass

    db_ids      = query_distinct_category_ids()
    saved_names = query_category_names()
    all_ids: List[int] = sorted(
        set(list(config_cat_map.keys()) + db_ids + list(saved_names.keys()))
    )

    if not all_ids:
        st.info("No category IDs found yet — they appear once tickets are created.")
        return

    st.markdown(f"**{len(all_ids)} category ID{'s' if len(all_ids) != 1 else ''} known**")

    for cat_id in all_ids:
        default_name = saved_names.get(cat_id) or config_cat_map.get(cat_id) or ""
        display_label = saved_names.get(cat_id) or config_cat_map.get(cat_id) or "unnamed"
        with st.expander(f"`{cat_id}` — {display_label}", expanded=False):
            new_name = st.text_input(
                "Friendly name",
                value=default_name,
                key=f"cat_name_{cat_id}",
            ).strip()
            col_s, col_d, _ = st.columns([1, 1, 3])
            with col_s:
                if st.button("Save", key=f"cat_save_{cat_id}", type="primary"):
                    if not new_name:
                        st.warning("Name cannot be empty.")
                    else:
                        try:
                            upsert_category_name(cat_id, new_name, me)
                            log_admin_action(me, "rename_category", f"id={cat_id} name={new_name}")
                            st.success(f"Saved `{new_name}` for {cat_id}.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed: {exc}")
            with col_d:
                if cat_id in saved_names:
                    if st.button("Clear override", key=f"cat_del_{cat_id}"):
                        try:
                            delete_category_name(cat_id)
                            log_admin_action(me, "clear_category_name", f"id={cat_id}")
                            st.success("Override cleared.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed: {exc}")


# ─── 7. Bot Config Editor (tech only) ────────────────────────────────────────

# Keys that must never be exposed in the config editor UI
_CONFIG_HIDDEN_KEYS = {
    "token", "DISCORD_CLIENT_SECRET", "DISCORD_CLIENT_ID", "DISCORD_REDIRECT_URI",
    "guild_id", "owners", "log_channel_id", "mention_channel_id", "update_channel_id",
}


def render_bot_config_editor() -> None:
    st.subheader("Bot Config Editor")
    st.caption(
        "Tech-only. Overrides are saved to the database. "
        "Apply them to `config/config.json` and redeploy the bot to take effect."
    )

    if not MYSQL_AVAILABLE:
        st.error("MySQL not available.")
        return

    discord_auth = st.session_state.get("discord_auth") or {}
    me = (discord_auth.get("user") or {}).get("username") or "unknown"

    # Load config.json for reference
    config_json_path = APP_ROOT / "config" / "config.json"
    raw_config: Dict[str, Any] = {}
    try:
        with open(config_json_path, "r", encoding="utf-8") as fh:
            raw_config = json.load(fh)
    except Exception:
        st.warning("Could not read config/config.json — showing DB overrides only.")

    safe_config = {k: v for k, v in raw_config.items() if k not in _CONFIG_HIDDEN_KEYS}
    db_overrides = query_bot_config_overrides()

    # Add / update override
    with st.expander("Add / update config override", expanded=False):
        o_key = st.text_input("Config key", key="cfg_key").strip()
        o_val = st.text_area("Value (JSON or plain string)", key="cfg_val", height=80).strip()
        if st.button("Save override", key="cfg_save_btn", type="primary"):
            if not o_key:
                st.warning("Key cannot be empty.")
            elif o_key in _CONFIG_HIDDEN_KEYS:
                st.error("That key is protected and cannot be overridden here.")
            else:
                try:
                    upsert_bot_config(o_key, o_val, me)
                    log_admin_action(me, "config_override", f"key={o_key}")
                    st.success(f"Override saved: `{o_key}`.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {exc}")

    st.divider()

    # Active DB overrides
    if db_overrides:
        st.markdown("**Active DB overrides**")
        for k, v in sorted(db_overrides.items()):
            with st.expander(f"`{k}`", expanded=False):
                edited_v = st.text_area("Value", value=v, key=f"cfg_ov_{k}", height=80)
                col_s, col_d, _ = st.columns([1, 1, 3])
                with col_s:
                    if st.button("Update", key=f"cfg_upd_{k}", type="primary"):
                        try:
                            upsert_bot_config(k, edited_v.strip(), me)
                            log_admin_action(me, "config_override_update", f"key={k}")
                            st.success("Updated.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed: {exc}")
                with col_d:
                    if st.button("Delete", key=f"cfg_del_{k}"):
                        try:
                            delete_bot_config(k)
                            log_admin_action(me, "config_override_delete", f"key={k}")
                            st.success("Deleted.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed: {exc}")
        st.divider()
    else:
        st.info("No active overrides yet.")

    # Reference: current config.json safe fields
    if safe_config:
        with st.expander("Current config.json (read-only reference)", expanded=False):
            st.json(safe_config)


# ─── 8. Staff Role List ───────────────────────────────────────────────────────

def render_staff_roles_section() -> None:
    st.subheader("Staff Role List")
    st.caption("Discord role IDs and their access levels in this dashboard.")

    rows = [
        {
            "Role":     "Jr. Mod",
            "Role ID":  "1334289756539846656",
            "Dashboard Access": "Viewer (Overview, Logs, Transcripts)",
            "Admin UI": "No",
            "Tech UI":  "No",
        },
        {
            "Role":     "Mod",
            "Role ID":  "1243559774847766619",
            "Dashboard Access": "Viewer",
            "Admin UI": "No",
            "Tech UI":  "No",
        },
        {
            "Role":     "Admin",
            "Role ID":  "1243929060145631262",
            "Dashboard Access": "Full admin dashboard",
            "Admin UI": "Yes",
            "Tech UI":  "No",
        },
        {
            "Role":     "Owner",
            "Role ID":  "1240455108047671406",
            "Dashboard Access": "Full admin dashboard",
            "Admin UI": "Yes",
            "Tech UI":  "No",
        },
        {
            "Role":     "Tech",
            "Role ID":  "1243929202785386527",
            "Dashboard Access": "Full admin dashboard + Bot Config Editor",
            "Admin UI": "Yes",
            "Tech UI":  "Yes",
        },
    ]

    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception:
        st.table(rows)


# ─── 9. Admin Action Log ──────────────────────────────────────────────────────

def render_admin_log_section() -> None:
    st.subheader("Admin Action Log")
    st.caption("Recent actions performed through this dashboard.")

    if not MYSQL_AVAILABLE:
        st.error("MySQL not available.")
        return

    with st.spinner("Loading…"):
        log_rows = query_admin_action_log(100)

    if not log_rows:
        st.info("No admin actions recorded yet.")
        return

    st.caption(f"Showing last {len(log_rows)} actions (newest first).")
    display = [
        {
            "#":      r.get("id", ""),
            "By":     r.get("performed_by", ""),
            "Action": r.get("action_type", ""),
            "Details":r.get("details", ""),
            "Time":   str(r.get("performed_at", ""))[:19],
        }
        for r in log_rows
    ]
    try:
        import pandas as pd
        df = pd.DataFrame(display)
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception:
        st.table(display)


def render_logs_view(tickets: List[Dict[str, Any]], transcript_map: Dict[str, Path], db_transcripts_map: Dict[str, Dict[str, Any]], is_admin: bool = False):
    st.subheader("Logs")

    # ── Search bar (user search) ──────────────────────────────────────────────
    search_query = st.text_input(
        "Search tickets by username or user ID",
        placeholder="e.g. moussecake or 123456789012345678",
        key="logs_search_q",
    ).strip()

    if search_query:
        if not MYSQL_AVAILABLE:
            st.error("MySQL not available.")
            return
        with st.spinner("Searching…"):
            results = query_user_tickets(search_query)
        if not results:
            st.info("No tickets found for that user.")
            return
        st.success(f"{len(results)} ticket{'s' if len(results) != 1 else ''} found")
        public_base_url = os.getenv("STREAMLIT_PUBLIC_URL", "").rstrip("/")
        for t in results:
            channel_id = str(t.get("channel_id", ""))
            member     = t.get("member_username", "—")
            mod        = t.get("mod_username") or "Unassigned"
            status     = t.get("status", "")
            created    = str(t.get("created_at", ""))[:10]
            closed     = str(t.get("closed_at", "") or "")[:10] or "—"
            badge      = "🟢" if status == "open" else "⚫"
            relative_link = f"?section=logs&channel={quote(channel_id)}"
            copy_link = f"{public_base_url}/{relative_link}" if public_base_url else relative_link
            st.markdown(f"{badge} **#{channel_id}** · user: `{member}` · mod: {mod} · created: {created} · closed: {closed}")
            col_open, col_copy = st.columns([0.25, 0.75])
            with col_open:
                st.link_button("Open Transcript", relative_link, key=f"srch_link_{channel_id}")
            with col_copy:
                st.text_input("Copy link", value=copy_link, key=f"srch_copy_{channel_id}", label_visibility="collapsed")
            st.divider()
        return

    if not tickets:
        st.info("No tickets found in database.")
        return

    open_tickets = [t for t in tickets if str(t.get("status", "")).lower() == "open"]
    closed_tickets = [t for t in tickets if str(t.get("status", "")).lower() == "closed"]

    # Use exact DB counts for tab labels — the ticket list is capped at 500 rows
    # so len(open_tickets)/len(closed_tickets) would under-report on large datasets.
    exact_counts = query_exact_ticket_counts()
    open_label   = f"Open ({exact_counts['open']})"
    closed_label = f"Closed ({exact_counts['closed']})"

    tab_open, tab_closed, tab_monitor = st.tabs([
        open_label,
        closed_label,
        "Open Ticket Monitor",
    ])

    def render_ticket_list(items: List[Dict[str, Any]]):
        if not items:
            st.write("No tickets in this category.")
            return
        public_base_url = os.getenv("STREAMLIT_PUBLIC_URL", "").rstrip("/")
        for ticket in items:
            channel_id = str(ticket.get("channel_id"))
            member = ticket.get("member_username", "Unknown")
            mod = ticket.get("mod_username") or "Unassigned"
            created = ticket.get("created_at", "")
            category = str(ticket.get("category") or ticket.get("category_id") or "")
            category_str = f" · {category}" if category else ""
            relative_link = f"?section=logs&channel={quote(channel_id)}"
            copy_link = f"{public_base_url}/{relative_link}" if public_base_url else relative_link
            has_transcript = channel_id in transcript_map or channel_id in db_transcripts_map
            st.markdown(f"**#{channel_id}** · {member} · mod: {mod} · created: {created}{category_str}")
            col_open, col_copy = st.columns([0.25, 0.75])
            with col_open:
                st.link_button("Open Transcript", relative_link)
            with col_copy:
                st.text_input(
                    "Copy link",
                    value=copy_link,
                    key=f"copy_link_{channel_id}_{ticket.get('status', 'unknown')}",
                    label_visibility="collapsed",
                )
            if not has_transcript:
                st.caption("Transcript file not found yet for this ticket.")

    with tab_open:
        render_ticket_list(open_tickets)
    with tab_closed:
        render_ticket_list(closed_tickets)
    with tab_monitor:
        if is_admin:
            render_open_tickets_monitor()
        else:
            st.info("Admin access required.")


def render_transcript_view(
    transcript_map: Dict[str, Path],
    db_transcripts_map: Dict[str, Dict[str, Any]],
    image_root: Path,
    staff_identifiers: List[str],
    show_internal: bool,
    internal_markers: List[str],
    preselected_channel: str,
):
    st.subheader("Transcript View")
    inject_transcript_styles()
    available_channel_ids = sorted(set(list(transcript_map.keys()) + list(db_transcripts_map.keys())), reverse=True)

    if not available_channel_ids:
        st.warning("No transcript files found.")
        return

    default_index = 0
    if preselected_channel and preselected_channel in available_channel_ids:
        default_index = available_channel_ids.index(preselected_channel)

    selected_channel = st.selectbox("Select ticket channel", available_channel_ids, index=default_index)
    transcript_json: Dict[str, Any] = {}
    messages = []
    if selected_channel in transcript_map:
        selected_path = transcript_map[selected_channel]
        st.caption(f"Transcript file: {selected_path}")
        if selected_path.suffix.lower() == ".json":
            transcript_json = load_transcript_json(selected_path)
            messages = transcript_json.get("messages", []) if isinstance(transcript_json, dict) else []
        else:
            raw = load_transcript_file(selected_path)
            messages = parse_transcript(raw)
            transcript_json = {"ticket": {"channel_id": selected_channel}, "messages": messages}
    else:
        transcript_json = db_transcripts_map.get(selected_channel, {})
        st.caption("Transcript source: database")
        messages = transcript_json.get("messages", []) if isinstance(transcript_json, dict) else []

    if not messages:
        st.info("Transcript is empty or could not be parsed.")
        return

    ticket = transcript_json.get("ticket", {}) if isinstance(transcript_json, dict) else {}

    left_col, right_col = st.columns([1.0, 2.2], gap="large")
    with left_col:
        render_ticket_summary_panel(ticket, messages, staff_identifiers)

    with right_col:
        category = ticket.get("category") or "Transcript"
        st.markdown(f"## {category}")

        # ── Filters ─────────────────────────────────────────────────────────
        all_authors = sorted({str(m.get("author", "")) for m in messages if m.get("author")})

        fc1, fc2 = st.columns([3, 2])
        with fc1:
            search_query = st.text_input(
                "Search",
                placeholder="Search content or author…",
                key=f"search_{selected_channel}",
            )
        with fc2:
            selected_authors = st.multiselect(
                "Author",
                all_authors,
                placeholder="All authors",
                key=f"authors_{selected_channel}",
            )

        # Date range — only rendered when the conversation spans multiple days
        ts_values = [
            parse_iso_timestamp(m.get("timestamp") or m.get("ts", ""))
            for m in messages
        ]
        valid_ts = [t for t in ts_values if t is not None]
        date_from = date_to = None
        date_range_changed = False
        if valid_ts:
            min_date = min(t.date() for t in valid_ts)
            max_date = max(t.date() for t in valid_ts)
            if min_date != max_date:
                dc1, dc2, _ = st.columns([1, 1, 2])
                date_from = dc1.date_input(
                    "From", value=min_date, min_value=min_date, max_value=max_date,
                    key=f"df_{selected_channel}",
                )
                date_to = dc2.date_input(
                    "To", value=max_date, min_value=min_date, max_value=max_date,
                    key=f"dt_{selected_channel}",
                )
                date_range_changed = date_from != min_date or date_to != max_date

        filters_active = bool(search_query or selected_authors or date_range_changed)

        def apply_filters(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            out = msgs
            if search_query:
                q = search_query.lower()
                out = [
                    m for m in out
                    if q in str(m.get("content", "")).lower()
                    or q in str(m.get("author", "")).lower()
                ]
            if selected_authors:
                out = [m for m in out if str(m.get("author", "")) in selected_authors]
            if date_from and date_to:
                def _in_range(m: Dict[str, Any]) -> bool:
                    ts = parse_iso_timestamp(m.get("timestamp") or m.get("ts", ""))
                    return ts is None or date_from <= ts.date() <= date_to
                out = [m for m in out if _in_range(m)]
            return out

        # Apply filters to each tab bucket
        conversation_messages = apply_filters(filter_messages_by_kind(messages, internal_markers, staff_identifiers, {"user", "staff"}))
        user_messages         = apply_filters(filter_messages_by_kind(messages, internal_markers, staff_identifiers, {"user"}))
        staff_messages        = apply_filters(filter_messages_by_kind(messages, internal_markers, staff_identifiers, {"staff"}))
        internal_messages     = apply_filters(filter_messages_by_kind(messages, internal_markers, staff_identifiers, {"internal"}))

        total_visible = len(apply_filters(messages))
        if filters_active:
            st.caption(f"Showing **{total_visible}** of **{len(messages)}** messages")
        else:
            st.caption(f"**{len(messages)}** messages total")

        # ── Tabs ─────────────────────────────────────────────────────────────
        tab_conversation, tab_user, tab_staff, tab_internal = st.tabs(
            [
                f"Conversation ({len(conversation_messages)})",
                f"User Responses ({len(user_messages)})",
                f"Staff Replies ({len(staff_messages)})",
                f"Internal ({len(internal_messages)})",
            ]
        )

        with tab_conversation:
            if conversation_messages:
                render_messages_appy_style(conversation_messages, image_root, staff_identifiers, False, internal_markers)
            else:
                st.info("No messages match the current filters." if filters_active else "No user/staff conversation messages found.")

        with tab_user:
            if user_messages:
                render_messages_appy_style(user_messages, image_root, staff_identifiers, False, internal_markers)
            else:
                st.info("No messages match the current filters." if filters_active else "No user responses found.")

        with tab_staff:
            if staff_messages:
                render_messages_appy_style(staff_messages, image_root, staff_identifiers, False, internal_markers)
            else:
                st.info("No messages match the current filters." if filters_active else "No staff replies found.")

        with tab_internal:
            if internal_messages:
                render_messages_appy_style(internal_messages, image_root, staff_identifiers, True, internal_markers)
            else:
                st.info("No messages match the current filters." if filters_active else "No internal messages found.")


def query_custom_url(url: str):
    """Query arbitrary database via SQLAlchemy."""
    if not SQLALCHEMY_AVAILABLE:
        st.error("SQLAlchemy not installed. Database support unavailable.")
        return None
    try:
        engine = create_engine(url, connect_args={})
        insp = inspect(engine)
        for tbl in ("transcripts", "messages", "transcript_messages", "ticket_messages"):
            if insp.has_table(tbl):
                with engine.connect() as conn:
                    q = text(f"SELECT * FROM {tbl} ORDER BY created_at DESC LIMIT 500")
                    return conn.execute(q).fetchall()
        st.warning("No known transcript table found in DB (looked for transcripts/messages).")
    except Exception as e:
        st.error(f"DB error: {e}")
    return None

settings = get_discord_oauth_settings()


def main():
    st.set_page_config(page_title="Transcript Viewer", layout="wide")

    banner_path = APP_ROOT / "MOUSSEMAIL.png"
    if banner_path.exists():
        st.image(Image.open(banner_path), use_column_width=True)
    else:
        st.title("Transcript Viewer")
    discord_auth = ensure_discord_auth()
    discord_user = discord_auth.get("user", {})

    display_name = discord_user.get("global_name") or discord_user.get("username") or "Unknown user"

    # ── Sidebar: identity ────────────────────────────────────────────────────
    user_id = discord_user.get("id", "")
    avatar_hash = discord_user.get("avatar", "")
    username = discord_user.get("username", "")
    if user_id and avatar_hash:
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=80"
    else:
        avatar_url = "https://cdn.discordapp.com/embed/avatars/0.png"
    st.sidebar.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:12px;padding:6px 0 14px 0;">
            <img src="{avatar_url}" width="44" height="44" style="border-radius:50%;object-fit:cover;" />
            <div>
                <div style="font-weight:600;font-size:0.95rem;line-height:1.3;">{display_name}</div>
                <div style="font-size:0.78rem;opacity:0.55;">@{username}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.sidebar.button("Sign out", use_container_width=True, type="primary"):
        st.session_state.discord_auth = None
        st.rerun()

    st.sidebar.divider()

    # ── Sidebar: navigation ──────────────────────────────────────────────────
    query_section = normalize_query_value(st.query_params.get("section", ""))
    query_channel = normalize_query_value(st.query_params.get("channel", ""))

    is_admin = is_admin_user(discord_auth)
    is_tech  = is_tech_user(discord_auth)

    # Build the set of sections this user can access
    _valid_sections = {"overview", "logs"}
    if is_admin:
        _valid_sections.update({"stats", "blacklist", "categories", "premade", "roles", "admin_log"})
    if is_tech:
        _valid_sections.add("config")

    # Resolve section from URL (source of truth) then fall back to session state
    _qs = "logs" if query_section == "transcript" else (query_section if query_section in _valid_sections else "")
    if _qs:
        section_key = _qs
    else:
        section_key = st.session_state.get("section_key", "logs")
    st.session_state["section_key"] = section_key

    # ── Sidebar navigation CSS ───────────────────────────────────────────────
    st.markdown(
        """
        <style>
        /* Nav buttons inside expanders: inactive */
        [data-testid="stSidebar"] [data-testid="stExpander"] button[kind="secondary"] {
            border: 1px solid rgba(192, 16, 64, 0.22) !important;
            background: rgba(192, 16, 64, 0.06) !important;
            padding: 7px 12px !important;
            border-radius: 8px !important;
            font-size: 0.88rem !important;
            font-weight: 500 !important;
            color: #7a0028 !important;
            text-align: left !important;
            justify-content: flex-start !important;
            transition: background 0.15s, border-color 0.15s !important;
            margin: 2px 0 !important;
            box-shadow: none !important;
        }
        [data-testid="stSidebar"] [data-testid="stExpander"] button[kind="secondary"]:hover {
            background: rgba(192, 16, 64, 0.13) !important;
            border-color: rgba(192, 16, 64, 0.40) !important;
        }
        /* Nav buttons inside expanders: active */
        [data-testid="stSidebar"] [data-testid="stExpander"] button[kind="primary"] {
            background: rgba(192, 16, 64, 0.18) !important;
            color: #9A0830 !important;
            font-weight: 700 !important;
            box-shadow: inset 3px 0 0 #C01040 !important;
            border: 1px solid rgba(192, 16, 64, 0.32) !important;
            padding: 7px 12px !important;
            border-radius: 8px !important;
            font-size: 0.88rem !important;
            text-align: left !important;
            justify-content: flex-start !important;
            margin: 2px 0 !important;
        }
        [data-testid="stSidebar"] [data-testid="stExpander"] button[kind="primary"]:hover {
            background: rgba(192, 16, 64, 0.25) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    def _nav_item(label: str, key: str) -> None:
        btn_type = "primary" if section_key == key else "secondary"
        if st.button(label, key=f"nav_{key}", use_container_width=True, type=btn_type):
            st.session_state["section_key"] = key
            st.query_params["section"] = key
            if "channel" in st.query_params:
                del st.query_params["channel"]
            st.rerun()

    # ── Group: Transcript Management ─────────────────────────────────────────
    _tm_sections = {"overview", "logs", "stats"}
    with st.sidebar.expander("📋 Transcript Management", expanded=section_key in _tm_sections):
        _nav_item("Overview", "overview")
        _nav_item("Logs", "logs")
        if is_admin:
            _nav_item("Stats & Leaderboard", "stats")

    # ── Group: Server Management ──────────────────────────────────────────────
    if is_admin:
        _sm_sections = {"categories", "premade", "blacklist"}
        with st.sidebar.expander("⚙️ Server Management", expanded=section_key in _sm_sections):
            _nav_item("Category Management", "categories")
            _nav_item("Premade Messages", "premade")
            _nav_item("Blacklist", "blacklist")

    # ── Group: Admin ──────────────────────────────────────────────────────────
    if is_admin or is_tech:
        _adm_sections = {"roles", "admin_log", "config"}
        with st.sidebar.expander("🔐 Admin", expanded=section_key in _adm_sections):
            if is_admin:
                _nav_item("Staff Role List", "roles")
                _nav_item("Admin Action Log", "admin_log")
            if is_tech:
                _nav_item("Bot Config Editor", "config")

    st.sidebar.divider()

    # ── Sidebar: advanced (collapsed) ────────────────────────────────────────
    tdir = find_dir(DEFAULT_TRANSCRIPT_DIRS)
    img_root = find_dir(DEFAULT_IMAGE_DIRS)
    transcript_map = list_transcript_files(tdir)
    db_transcripts_map = query_mysql_transcripts_map()
    tickets = query_mysql_tickets() or []

    with st.sidebar.expander("Advanced", expanded=False):
        staff_ids_input = st.text_input("Staff identifier substrings", value="mod,staff,admin,mousse", help="Comma-separated substrings used to identify staff authors in transcripts.")
        internal_markers_input = st.text_input("Internal note markers", value="internal,note,staff-only", help="Comma-separated markers that flag a message as internal.")
        show_internal = st.toggle("Show internal notes", value=False)
        st.caption(f"Transcripts dir: `{tdir}`")
        st.caption(f"Local: {len(transcript_map)} · DB: {len(db_transcripts_map)}")

    staff_identifiers = [s.strip() for s in staff_ids_input.split(",") if s.strip()]
    internal_markers = [s.strip() for s in internal_markers_input.split(",") if s.strip()]

    if section_key == "overview":
        st.subheader("Overview")
        open_count = sum(1 for t in tickets if str(t.get("status", "")).lower() == "open")
        closed_count = sum(1 for t in tickets if str(t.get("status", "")).lower() == "closed")
        total_transcripts = len(set(list(transcript_map.keys()) + list(db_transcripts_map.keys())))
        metrics = compute_staff_overview_metrics(tickets, db_transcripts_map, discord_auth)

        # ── Server stats ──────────────────────────────────────────────────────
        st.markdown("**Server stats**")
        c1, c2, c3 = st.columns(3)
        c1.metric("Open tickets", open_count)
        c2.metric("Closed tickets", closed_count)
        c3.metric("Total transcripts", total_transcripts)

        st.divider()

        # ── Your activity ─────────────────────────────────────────────────────
        st.markdown(f"**Your activity** · {display_name}")
        a1, a2, a3 = st.columns(3)
        a1.metric("Open assigned", metrics["assigned_open"])
        a2.metric("Closed by you", metrics["closed_by_you"])
        a3.metric("Assigned & closed", metrics["assigned_closed"])

        b1, b2, b3 = st.columns(3)
        b1.metric("Your replies", metrics["staff_replies"])
        b2.metric("Tickets handled", metrics["handled_tickets"])

        st.divider()
        st.caption("Use **Logs** to browse tickets and open full transcripts")

        # Meme image — because modmail life 💀
        meme_path = APP_ROOT / "image.png"
        if meme_path.exists():
            st.markdown("")
            _, meme_col, _ = st.columns([1, 2, 1])
            with meme_col:
                st.image(Image.open(meme_path), caption="the modmail experience", use_column_width=True)

    elif section_key == "logs":
        if query_channel:
            if st.button("← Back to Logs"):
                try:
                    del st.query_params["channel"]
                except Exception:
                    pass
                st.rerun()
            render_transcript_view(
                transcript_map,
                db_transcripts_map,
                img_root,
                staff_identifiers,
                show_internal,
                internal_markers,
                query_channel,
            )
        else:
            logs_tab, transcripts_tab = st.tabs(["Logs", "Transcripts"])
            with logs_tab:
                render_logs_view(tickets, transcript_map, db_transcripts_map, is_admin=is_admin)
            with transcripts_tab:
                render_transcript_view(
                    transcript_map,
                    db_transcripts_map,
                    img_root,
                    staff_identifiers,
                    show_internal,
                    internal_markers,
                    "",
                )

    elif section_key == "premade" and is_admin:
        render_premade_messages_section()

    elif section_key == "stats" and is_admin:
        stats_tab, leaderboard_tab = st.tabs(["Stats Dashboard", "Staff Leaderboard"])
        with stats_tab:
            render_stats_dashboard()
        with leaderboard_tab:
            render_staff_leaderboard()

    elif section_key == "blacklist" and is_admin:
        render_blacklist_section()

    elif section_key == "categories" and is_admin:
        render_category_management()

    elif section_key == "roles" and is_admin:
        render_staff_roles_section()

    elif section_key == "admin_log" and is_admin:
        render_admin_log_section()

    elif section_key == "config" and is_tech:
        render_bot_config_editor()


if __name__ == "__main__":
    main()
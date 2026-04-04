import os
import re
import json
import secrets
import streamlit as st
from pathlib import Path
from PIL import Image
from typing import List, Dict, Any
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import datetime, timezone

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
APP_ROOT = Path(__file__).resolve().parent

# MySQL Database configuration (same as bot)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "gameswaw5.bisecthosting.com"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u1079393_bwVUJntzFf"),
    "password": os.getenv("DB_PASS", "XzaXNWotYim7AWlIeudHjSoO"),
    "database": os.getenv("DB_NAME", "s1079393_ModMail"),
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

            st.session_state.discord_auth = {
                "access_token": access_token,
                "user": user,
            }
            clear_auth_query_params()
            st.rerun()
        except Exception as e:
            st.error(f"Discord login failed: {e}")
            st.stop()

    if st.session_state.discord_auth:
        return st.session_state.discord_auth

    st.sidebar.write("🔐 Staff sign-in")
    st.sidebar.caption("Sign in with Discord. Access is limited to members with the required CCAC role.")
    login_state = secrets.token_urlsafe(24)
    st.sidebar.link_button("Sign in with Discord", build_discord_login_url(login_state))
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
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 12px;
            padding: 16px;
            background: rgba(23, 30, 52, 0.65);
        }
        .ticket-summary-row {
            margin-bottom: 12px;
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .ticket-summary-row:last-child {
            margin-bottom: 0;
            padding-bottom: 0;
            border-bottom: none;
        }
        .ticket-summary-label {
            font-size: 0.9rem;
            color: #c9d1e6;
            font-weight: 700;
        }
        .ticket-summary-value {
            margin-top: 4px;
            color: #f4f6ff;
        }
        .msg-card {
            border-left: 3px solid rgba(122, 162, 255, 0.65);
            border-radius: 8px;
            padding: 10px 12px;
            margin: 8px 0 14px;
            background: rgba(41, 52, 84, 0.45);
        }
        .msg-system {
            border-left-color: rgba(55, 221, 161, 0.9);
            background: rgba(31, 74, 67, 0.28);
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
            bubble_style = "background:#26345a;border-radius:10px;padding:13px 18px 13px 16px;box-shadow:0 2px 8px rgba(0,0,0,0.10);color:#f4f6ff;"
            align_style = "justify-content:flex-end;"
            avatar_col_idx, msg_col_idx = 1, 0
        elif is_system:
            bubble_style = "background:#1f4a43;border-radius:10px;padding:13px 18px 13px 16px;box-shadow:0 2px 8px rgba(0,0,0,0.10);color:#e6fff6;"
            align_style = "justify-content:flex-start;"
            avatar_col_idx, msg_col_idx = 0, 1
        else:
            bubble_style = "background:#23273a;border-radius:10px;padding:13px 18px 13px 16px;box-shadow:0 2px 8px rgba(0,0,0,0.10);color:#f4f6ff;"
            align_style = "justify-content:flex-start;"
            avatar_col_idx, msg_col_idx = 0, 1

        # Outer container for spacing between authors
        st.markdown(f"<div style='margin-top:{extra_top_margin}px;'></div>", unsafe_allow_html=True)
        row = st.columns([0.11, 0.89], gap="small")
        # Use flexbox to align staff messages to the right
        st.markdown(f"<div style='display:flex;{align_style}'>", unsafe_allow_html=True)
        if is_staff_msg:
            # Staff: right side (msg, then avatar)
            with row[1]:
                st.markdown(f"<div style='text-align:right;margin-bottom:2px;'><strong>{author}</strong> <span style='background:#7aa2ff;color:#fff;border-radius:6px;padding:2px 8px;font-size:0.85em;margin-left:8px;'>Staff</span></div>", unsafe_allow_html=True)
                st.markdown(
                    f"<div style='{bubble_style}margin-bottom:2px;min-width:60px;display:inline-block;text-align:left;'>"
                    f"{(content or '').replace(chr(10), '<br>')}"
                    f"</div>", unsafe_allow_html=True)
            with row[0]:
                st.image(avatar_url, width=44)
        else:
            # User/system: left side (avatar, then msg)
            with row[0]:
                st.image(avatar_url, width=44)
            with row[1]:
                if is_staff_msg:
                    st.markdown(f"<div style='margin-bottom:2px;'><strong>{author}</strong> <span style='background:#7aa2ff;color:#fff;border-radius:6px;padding:2px 8px;font-size:0.85em;margin-left:8px;'>Staff</span></div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='margin-bottom:2px;'><strong>{author}</strong></div>", unsafe_allow_html=True)
                st.markdown(
                    f"<div style='{bubble_style}margin-bottom:2px;min-width:60px;display:inline-block;'>"
                    f"{(content or '').replace(chr(10), '<br>')}"
                    f"</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

            embeds = msg.get("embeds", [])
            if not content and isinstance(embeds, list):
                for embed in embeds:
                    if not isinstance(embed, dict):
                        continue
                    embed_title = embed.get("title", "")
                    embed_author = embed.get("author", "")
                    embed_description = embed.get("description", "")
                    embed_fields = embed.get("fields", [])

                    if embed_title:
                        st.markdown(f"**{embed_title}**")
                    if embed_author:
                        st.caption(embed_author)
                    if embed_description:
                        st.write(embed_description)
                    if isinstance(embed_fields, list):
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


def render_logs_view(tickets: List[Dict[str, Any]], transcript_map: Dict[str, Path], db_transcripts_map: Dict[str, Dict[str, Any]]):
    st.subheader("Logs")
    if not tickets:
        st.info("No tickets found in database.")
        return

    open_tickets = [t for t in tickets if str(t.get("status", "")).lower() == "open"]
    closed_tickets = [t for t in tickets if str(t.get("status", "")).lower() == "closed"]

    tab_open, tab_closed = st.tabs([f"Open ({len(open_tickets)})", f"Closed ({len(closed_tickets)})"])

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
            relative_link = f"?section=transcript&channel={quote(channel_id)}"
            copy_link = f"{public_base_url}/{relative_link}" if public_base_url else relative_link
            has_transcript = channel_id in transcript_map or channel_id in db_transcripts_map
            icon = "🟢" if str(ticket.get("status", "")).lower() == "open" else "🔴"
            st.markdown(f"{icon} **#{channel_id}** · {member} · mod: {mod} · created: {created}")
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
        st.write(f"Messages: **{len(messages)}**")
        conversation_messages = filter_messages_by_kind(messages, internal_markers, staff_identifiers, {"user", "staff"})
        user_messages = filter_messages_by_kind(messages, internal_markers, staff_identifiers, {"user"})
        staff_messages = filter_messages_by_kind(messages, internal_markers, staff_identifiers, {"staff"})
        internal_messages = filter_messages_by_kind(messages, internal_markers, staff_identifiers, {"internal"})

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
                st.info("No user/staff conversation messages found.")

        with tab_user:
            if user_messages:
                render_messages_appy_style(user_messages, image_root, staff_identifiers, False, internal_markers)
            else:
                st.info("No user responses found.")

        with tab_staff:
            if staff_messages:
                render_messages_appy_style(staff_messages, image_root, staff_identifiers, False, internal_markers)
            else:
                st.info("No staff replies found.")

        with tab_internal:
            if internal_messages:
                render_messages_appy_style(internal_messages, image_root, staff_identifiers, True, internal_markers)
            else:
                st.info("No internal messages found.")


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
st.write("Redirect URI being used:", settings["redirect_uri"])

def main():
    st.set_page_config(page_title="Transcript Viewer", layout="wide")
    st.title("📋 Transcript Viewer")
    discord_auth = ensure_discord_auth()
    discord_user = discord_auth.get("user", {})

    display_name = discord_user.get("global_name") or discord_user.get("username") or "Unknown user"
    st.sidebar.success(f"✅ Signed in as {display_name}")
    st.sidebar.caption(f"Guild: {CCAC_MAIN_GUILD_ID} · Required roles: Jr. Mod / Mod / Admin / Owner / Tech")
    if st.sidebar.button("Sign out"):
        st.session_state.discord_auth = None
        st.rerun()

    query_section = normalize_query_value(st.query_params.get("section", ""))
    query_channel = normalize_query_value(st.query_params.get("channel", ""))

    section_labels = {
        "overview": "Overview",
        "logs": "Logs",
        "transcript": "Transcript View",
    }
    default_section_key = query_section if query_section in section_labels else "logs"
    section_key = st.sidebar.radio(
        "Category",
        ("overview", "logs", "transcript"),
        index=("overview", "logs", "transcript").index(default_section_key),
        format_func=lambda key: section_labels[key],
    )

    staff_ids_input = st.sidebar.text_input("Staff identifier substrings (comma-separated)", value="mod,staff,admin,mousse")
    staff_identifiers = [s.strip() for s in staff_ids_input.split(",") if s.strip()]

    internal_markers_input = st.sidebar.text_input("Internal note markers (comma-separated)", value="internal,note,staff-only")
    internal_markers = [s.strip() for s in internal_markers_input.split(",") if s.strip()]

    show_internal = st.sidebar.toggle("Show internal notes", value=False)

    tdir = find_dir(DEFAULT_TRANSCRIPT_DIRS)
    img_root = find_dir(DEFAULT_IMAGE_DIRS)
    transcript_map = list_transcript_files(tdir)
    db_transcripts_map = query_mysql_transcripts_map()
    tickets = query_mysql_tickets() or []

    st.sidebar.caption(f"Transcripts dir: {tdir}")
    st.sidebar.caption(f"Detected local transcripts: {len(transcript_map)}")
    st.sidebar.caption(f"Detected DB transcripts: {len(db_transcripts_map)}")

    if section_key == "overview":
        st.subheader("Overview")
        open_count = sum(1 for t in tickets if str(t.get("status", "")).lower() == "open")
        closed_count = sum(1 for t in tickets if str(t.get("status", "")).lower() == "closed")
        metrics = compute_staff_overview_metrics(tickets, db_transcripts_map, discord_auth)
        st.caption(f"Personal metrics for {display_name}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Open tickets", open_count)
        c2.metric("Closed tickets", closed_count)
        c3.metric("Transcripts", len(set(list(transcript_map.keys()) + list(db_transcripts_map.keys()))))
        c4, c5, c6, c7, c8 = st.columns(5)
        c4.metric("Your open tickets", metrics["assigned_open"])
        c5.metric("Your closed tickets", metrics["closed_by_you"])
        c6.metric("Your assigned closed", metrics["assigned_closed"])
        c7.metric("Your staff replies", metrics["staff_replies"])
        c8.metric("Tickets you handled", metrics["handled_tickets"])
        st.write("Use **Logs** to browse ticket status and open transcript links.")
        st.write("Use **Transcript View** to read full conversation history.")

    elif section_key == "logs":
        render_logs_view(tickets, transcript_map, db_transcripts_map)

    elif section_key == "transcript":
        render_transcript_view(
            transcript_map,
            db_transcripts_map,
            img_root,
            staff_identifiers,
            show_internal,
            internal_markers,
            query_channel,
        )


if __name__ == "__main__":
    main()
import os
import re
import json
import streamlit as st
from pathlib import Path
from PIL import Image
from typing import List, Dict, Any
from urllib.parse import quote
from datetime import datetime, timezone


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

# MySQL Database configuration (same as bot)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "gameswaw5.bisecthosting.com"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u1079393_bwVUJntzFf"),
    "password": os.getenv("DB_PASS", "XzaXNWotYim7AWlIeudHjSoO"),
    "database": os.getenv("DB_NAME", "s1079393_ModMail"),
}


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
    closed_by = infer_closed_by(messages, staff_identifiers)
    members_value = f"{owner_name}, {closed_by}" if closed_by != owner_name else owner_name

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
                <div class="ticket-summary-value">{closed_by}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def normalize_display_message(msg: Dict[str, Any]):
    author = str(msg.get("author", "Unknown") or "Unknown")
    content = str(msg.get("content", "") or "")

    lines = [line for line in content.splitlines()]
    if lines:
        first_line = lines[0].strip().lower()
        if first_line == "user message":
            if len(lines) >= 2 and lines[1].strip():
                author = lines[1].strip()
                lines = lines[2:]
            else:
                lines = lines[1:]
        elif first_line.startswith("staff response"):
            lines = lines[1:]

    normalized_content = "\n".join(lines).strip()
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
    for msg in messages:
        author, content = normalize_display_message(msg)
        internal = message_is_internal(msg, content, internal_markers)
        if internal and not show_internal:
            continue

        role = str(msg.get("role", "")).lower()
        ts = msg.get("ts") or msg.get("timestamp") or ""
        ts_label = relative_time_label(ts) or ts
        is_system = role == "system"

        avatar_url = get_avatar_url(msg, author)
        avatar_col, message_col = st.columns([0.09, 0.91], gap="small")
        with avatar_col:
            st.image(avatar_url, width=42)

        with message_col:
            st.markdown(f"**{author}**")
            if ts_label:
                st.caption(ts_label)

            card_class = "msg-card msg-system" if is_system else "msg-card"
            st.markdown(f"<div class='{card_class}'>{(content or '').replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)

            embeds = msg.get("embeds", [])
            # Avoid duplicate rendering when embed text was already folded into content.
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
            "SELECT channel_id, transcript_json FROM ticket_transcripts ORDER BY updated_at DESC LIMIT 2000"
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
        render_messages_appy_style(messages, image_root, staff_identifiers, show_internal, internal_markers)


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





def main():
    st.set_page_config(page_title="Transcript Viewer", layout="wide")
    st.title("📋 Transcript Viewer")

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    pwd_env = os.getenv("STREAMLIT_STAFF_PASSWORD")
    try:
        pwd_secret = st.secrets.get("staff_password") if hasattr(st, "secrets") else None
    except Exception:
        pwd_secret = None
    staff_password = pwd_env or pwd_secret

    if not st.session_state.authenticated:
        with st.sidebar.form("login"):
            st.write("🔐 Staff sign-in")
            pwd = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")
            if submitted:
                if staff_password and pwd == staff_password:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Invalid password. Set STREAMLIT_STAFF_PASSWORD or staff_password in secrets.")
        st.stop()

    st.sidebar.success("✅ Authenticated")

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
        c1, c2, c3 = st.columns(3)
        c1.metric("Open tickets", open_count)
        c2.metric("Closed tickets", closed_count)
        c3.metric("Transcripts", len(set(list(transcript_map.keys()) + list(db_transcripts_map.keys()))))
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
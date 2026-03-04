import os
import re
import streamlit as st
from pathlib import Path
from PIL import Image
from typing import List, Dict, Any

try:
    from sqlalchemy import create_engine, inspect, text
    SQLALCHEMY_AVAILABLE = True
except Exception:
    SQLALCHEMY_AVAILABLE = False


DEFAULT_TRANSCRIPT_DIRS = ["transcripts", "logs"]
DEFAULT_IMAGE_DIRS = ["transcripts/images", "logs/images", "images"]


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


def render_messages(messages: List[Dict[str, Any]], image_root: Path, staff_identifiers: List[str], show_internal: bool, internal_markers: List[str]):
    for msg in messages:
        internal = is_internal(msg.get("content", ""), internal_markers)
        if internal and not show_internal:
            continue

        staff = is_staff(msg.get("author", ""), staff_identifiers)

        cols = st.columns([0.12, 0.88])
        with cols[0]:
            if staff:
                st.markdown("**Staff**")
            else:
                st.markdown("**User**")
        with cols[1]:
            st.markdown(f"**{msg.get('author','')}** — _{msg.get('ts','')}_")
            st.write(msg.get("content", ""))
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


def try_query_db(url: str):
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
    st.title("Transcript Viewer")

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
            st.write("Staff sign-in")
            pwd = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")
            if submitted:
                if staff_password and pwd == staff_password:
                    st.session_state.authenticated = True
                    st.experimental_rerun()
                else:
                    st.error("Invalid password. Set STREAMLIT_STAFF_PASSWORD or staff_password in secrets.")
        st.stop()

    st.sidebar.success("Authenticated")

    source = st.sidebar.radio("Data source", ("Local files", "Database"))

    staff_ids_input = st.sidebar.text_input("Staff identifier substrings (comma-separated)", value="mod,staff,admin")
    staff_identifiers = [s.strip() for s in staff_ids_input.split(",") if s.strip()]

    internal_markers_input = st.sidebar.text_input("Internal note markers (comma-separated)", value="internal,note,staff-only")
    internal_markers = [s.strip() for s in internal_markers_input.split(",") if s.strip()]

    show_internal = st.sidebar.checkbox("Show internal notes", value=False)

    if source == "Local files":
        tdir = find_dir(DEFAULT_TRANSCRIPT_DIRS)
        img_root = find_dir(DEFAULT_IMAGE_DIRS)
        st.sidebar.markdown(f"Transcripts dir: {tdir}")
        files = [p for p in tdir.glob("*.txt")] if tdir.exists() else []
        if not files:
            st.warning(f"No transcript files found in {tdir}.")
            return
        choice = st.selectbox("Transcript file", options=sorted(files), format_func=lambda p: p.name)
        raw = load_transcript_file(choice)
        messages = parse_transcript(raw)
        st.sidebar.markdown(f"Messages: {len(messages)}")
        render_messages(messages, img_root, staff_identifiers, show_internal, internal_markers)

    else:
        db_url = st.sidebar.text_input("Database URL (SQLAlchemy) e.g. postgresql://user:pass@host/db")
        if not db_url:
            st.info("Provide DATABASE URL to enable DB mode.")
            return
        rows = try_query_db(db_url)
        if not rows:
            return
        for r in rows:
            d = dict(r)
            author = d.get("author") or d.get("username") or d.get("sender") or ""
            ts = d.get("created_at") or d.get("timestamp") or ""
            content = d.get("content") or d.get("message") or ""
            images = []
            attachments = []
            if "attachment" in d:
                attachments = [d.get("attachment")]
            st.markdown(f"**{author}** — _{ts}_")
            st.write(content)
            st.markdown("---")


if __name__ == "__main__":
    main()

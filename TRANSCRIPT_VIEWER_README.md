# Streamlit Transcript Viewer

A staff-only Streamlit app for viewing and searching Discord modmail transcripts with images, attachments, and internal note management.

## Features

✅ **Local Transcript Viewing** – Reads `.txt` transcript files from `transcripts/` or `logs/`  
✅ **Image Rendering** – Automatically embeds saved images from `transcripts/images/`  
✅ **Message Separation** – Distinguishes user vs. staff messages based on author names  
✅ **Internal Toggle** – Hide/show internal staff notes with a UI checkbox  
✅ **Optional DB Support** – Query PostgreSQL/MySQL transcripts via SQLAlchemy  
✅ **Staff Authentication** – Password-protected access  
✅ **Attachment Links** – Clickable external attachment links  

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set staff password (choose one):**

   **Option A: Environment variable**
   ```bash
   export STREAMLIT_STAFF_PASSWORD="your_password"
   ```

   **Option B: `.streamlit/secrets.toml`**
   ```toml
   staff_password = "your_password"
   ```

3. **Run the app:**
   ```bash
   streamlit run streamlit_transcripts.py
   ```

## Usage

### Local Files Mode (Default)
- Automatically discovers transcript files in `transcripts/` or `logs/`
- Images stored in `transcripts/images/` are embedded inline
- Select a transcript from the dropdown

### Database Mode
- Provide a SQLAlchemy connection string (e.g., `postgresql://user:pass@localhost/modmail`)
- Supports any table named `transcripts`, `messages`, `transcript_messages`, or `ticket_messages`
- Expects columns: `author` (or `username`), `created_at` (or `timestamp`), `content` (or `message`)

### Sidebar Controls

| Control | Purpose |
|---------|---------|
| **Data source** | Toggle between local files and database |
| **Staff identifier substrings** | Comma-separated list (e.g. "mod,staff,admin") to mark messages as staff |
| **Internal note markers** | Comma-separated list (e.g. "internal,note,staff-only") to flag messages as internal |
| **Show internal notes** | Checkbox to display/hide flagged messages |

## Transcript File Format

The bot saves transcripts as plain text with metadata:

```
[2026-03-04 14:23:45.123000+00:00] User#1234: Hello, I need help
[Image saved: transcripts/images/1234567890_12345_screenshot.png]

[2026-03-04 14:24:15.456000+00:00] ModStaff#5678: I can help with that
[Attachment: https://discord.com/api/webhooks/...]

```

The parser extracts messages, timestamps, images, and attachments automatically.

## Configuration

### Transcript Directories
Edit the `DEFAULT_TRANSCRIPT_DIRS` and `DEFAULT_IMAGE_DIRS` in `streamlit_transcripts.py` if your structure differs:

```python
DEFAULT_TRANSCRIPT_DIRS = ["transcripts", "logs"]  # searched in order
DEFAULT_IMAGE_DIRS = ["transcripts/images", "logs/images", "images"]
```

### Staff Identifier Logic
Messages are marked as "Staff" if the author name contains any substring from the sidebar setting (case-insensitive).

### Internal Note Detection
Messages are marked as "Internal" if the content contains any substring from the sidebar setting (case-insensitive).

## Database Integration

If your bot eventually saves transcripts directly to PostgreSQL, connect with:

```
postgresql://username:password@localhost:5432/modmail_db
```

The app will automatically detect and query the transcript table.

## Troubleshooting

**"No transcript files found"**  
Check that transcript files (`.txt`) exist in `transcripts/` and images in `transcripts/images/`.

**"Image not found"**  
Ensure the bot's `IMAGE_DIR` config matches the `DEFAULT_IMAGE_DIRS` in the app.

**"DB error: no module named 'psycopg2'"**  
Install: `pip install psycopg2-binary sqlalchemy`

**Authentication loops**  
Set `STREAMLIT_STAFF_PASSWORD` environment variable or add to `.streamlit/secrets.toml`.

## Development Notes

- The regex patterns for message parsing assume the bot's standard format `[timestamp] author: content`
- Image paths are resolved relative to the detected image root directory
- DB queries limit results to 500 messages for performance
- Multi-line messages are preserved in the "content" field

---

**See Also:**  
- [streamlit_transcripts.py](streamlit_transcripts.py) – Main app code
- [cogs/modmail.py](cogs/modmail.py#L190) – Bot's transcript generation
- [config.py](config.py) – Directories and staff roles

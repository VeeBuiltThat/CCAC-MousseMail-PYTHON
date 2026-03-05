# Streamlit Transcript Viewer

A staff-only Streamlit app for viewing and searching Discord modmail transcripts with images, attachments, and internal note management.

## Features

✅ **Local Transcript Viewing** – Reads channel transcript `.json` files (with `.txt` fallback) from `transcripts/` or `logs/`  
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

The bot now saves transcripts as structured JSON per channel (`<channel_id>.json`):

```json
{
   "ticket": {
      "channel_id": 1234567890,
      "channel_name": "dx-example",
      "category": "Appeals",
      "owner_id": 123456789012345678,
      "owner_name": "User#1234",
      "closed_at": "2026-03-05T12:34:56.000000+00:00"
   },
   "messages": [
      {
         "timestamp": "2026-03-05T12:00:00.000000+00:00",
         "author": "User#1234",
         "author_id": 123456789012345678,
         "role": "user",
         "content": "Hello, I need help",
         "images": ["transcripts/images/123...png"],
         "attachments": ["https://..."]
      }
   ]
}
```

Legacy `.txt` transcripts are still supported as fallback.

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
Check that transcript files (`.json` or legacy `.txt`) exist in `transcripts/` and images in `transcripts/images/`.

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

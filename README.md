# ModMail Bot
A lightweight Discord mod-mail / ticketing bot that lets users open private ticket channels by messaging the bot. Designed for small to medium servers where staff need a clear, private way to handle user inquiries.

## Table of contents
- Overview
- Features
- Requirements
- Installation (Windows)
- Configuration
- Usage
- Bot commands
- Transcript Viewer
- Development
- Troubleshooting
- Contributing
- License
- Contact
- Changelog

## Overview
Users can DM the bot to open a private ticket channel inside a configured category. Staff can reply, move tickets between categories, and use premade replies.

## Architecture

### Class Diagram

```mermaid
classDiagram
    class ModmailBot {
        +config: ConfigManager
        +db: DatabaseManager
        +threads: ThreadManager
        +note_manager: NoteManager
        +guild_id: int
        +loaded_cogs: list
        +on_ready()
        +on_error()
        +on_command_error()
        +timer_task()
        +load_extensions()
    }
    class ConfigManager {
        +cache: dict
        +populate_cache()
        +__getitem__(key)
    }
    class DatabaseManager {
        +conn
        +setup()
        +open_ticket()
        +close_ticket()
        +get_open_ticket_channel_id()
        +get_ticket_by_channel()
        +save_ticket_transcript()
        +add_note()
        +get_notes()
        +get_dx_response()
        +add_dx_response()
        +get_all_dx_responses()
        +add_watcher()
        +get_watchers()
        +add_ticket_timer()
        +cancel_ticket_timer()
        +get_pending_timers()
    }
    class ThreadManager {
        +create(user, message)
    }
    class NoteManager {
        +add_note(user_id, note, staff)
        +get_notes(user_id)
    }
    class Modmail {
        <<Cog>>
        +open_tickets: dict
        +delayed_closures: dict
        +suspended_tickets: dict
        +notify_watchers: dict
    }
    class StaffCommands {
        <<Cog>>
        +NotesView
        +TranscriptView
    }
    class CategoryManagement {
        <<Cog>>
    }

    ModmailBot *-- ConfigManager
    ModmailBot *-- DatabaseManager
    ModmailBot *-- ThreadManager
    ModmailBot *-- NoteManager
    ModmailBot o-- Modmail
    ModmailBot o-- StaffCommands
    ModmailBot o-- CategoryManagement
    NoteManager --> DatabaseManager : delegates to
```

### Ticket Lifecycle

```mermaid
sequenceDiagram
    participant User
    participant Bot as ModmailBot
    participant DB as DatabaseManager
    participant Ch as Discord Channel
    participant Staff

    User->>Bot: DM message
    Bot->>DB: get_open_ticket_channel_id(user_id)
    alt No open ticket
        Bot->>DB: open_ticket(user_id, channel_id, ...)
        Bot->>Ch: Create ticket channel
        Bot->>Staff: Notify (ping + ClaimTicketButton)
    else Ticket already open
        Bot->>Ch: Forward message to existing channel
    end

    Staff->>Ch: %r <reply>
    Bot->>User: DM reply

    opt Ticket suspended
        Bot->>Ch: %suspend
        Bot-->>Ch: Auto-close after 24h inactivity
    end

    Staff->>Ch: %close [delay]
    Bot->>DB: close_ticket(channel_id, closed_at)
    Bot->>DB: save_ticket_transcript(...)
    Bot->>Ch: Delete channel
    Bot->>User: DM "Your ticket has been closed"
```

## Features
- Ticket creation via DM
- Private ticket channels in configured categories
- Staff-only commands to reply, edit replies, move tickets
- Pre-made replies (dx)
- Config-driven (server IDs, category IDs, bot token)
- **Streamlit Transcript Viewer** — Staff-only web UI to browse, search, and filter transcripts with image rendering and internal note toggling
- **Logging** — Logs bot activity and errors to the `logs/` directory for easier debugging and monitoring.

## Requirements
- Python 3.10+ recommended
- pip
- Discord bot token (from the Discord Developer Portal)

## Installation (Windows)
1. Clone the repo:
   ```
   git clone https://github.com/VeeBuiltThat/CCAC-MousseMail-PYTHON.git
   cd CCAC-MousseMail-PYTHON
   ```
2. Create and activate a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Configuration
Create or update `config/config.json` with your settings. Minimal example:
```json
{
  "token": "YOUR_BOT_TOKEN",
  "guild_id": "GUILD_ID_HERE",
  "contact_category_id": "CONTACT_CATEGORY_ID_HERE",
  "staff_role_id": "STAFF_ROLE_ID_HERE",
  "prefix": "!"
}
```
- token: Discord bot token
- guild_id: your server ID
- contact_category_id: category where tickets are created
- staff_role_id: role allowed to use staff commands
- prefix: command prefix (default: "!")

Keep your token secret. Consider using environment variables or a secrets manager for production.

## Usage
Run the bot:
```
python bot.py
```
Then:
- Users DM the bot to create tickets.
- Staff open the ticket channel in the configured category to reply.

## Commands
(for staff; prefix = configured prefix)
- `%move <category>` — Move the current ticket channel to another category.
- `%r <message>` — Reply to the user associated with the ticket.
- `%re <message>` — Edit the previous reply to the user.
- `%dx` — Show pre-made replies / canned responses.

Adjust command names and behavior to match your bot's implementation if they differ.

## Database Schema

```mermaid
erDiagram
    active_tickets {
        BIGINT id PK
        BIGINT user_id
        BIGINT channel_id UK
        BIGINT category_id
        VARCHAR status
        BIGINT mod_id
        VARCHAR mod_username
        TINYINT notified
        BIGINT open_ticket_user_id
        DATETIME opened_at
        DATETIME closed_at
    }
    ticket_transcripts {
        BIGINT id PK
        BIGINT channel_id UK
        BIGINT guild_id
        VARCHAR guild_name
        VARCHAR channel_name
        VARCHAR category_name
        BIGINT owner_id
        VARCHAR owner_name
        VARCHAR opened_by
        VARCHAR closed_by
        DATETIME opened_at
        DATETIME closed_at
        LONGTEXT open_reason
        LONGTEXT close_reason
        INT message_count
        LONGTEXT transcript_json
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
    user_notes {
        BIGINT id PK
        BIGINT user_id
        LONGTEXT note
        VARCHAR staff
        TIMESTAMP created_at
    }
    dx_responses {
        INT id PK
        VARCHAR key UK
        LONGTEXT response
    }
    ticket_timers {
        INT id PK
        BIGINT channel_id
        BIGINT user_id
        VARCHAR action
        DATETIME execute_at
        VARCHAR status
    }
    ticket_watchers {
        BIGINT channel_id
        BIGINT mod_id
    }

    active_tickets ||--o| ticket_transcripts : "archived on close"
    active_tickets ||--o{ ticket_watchers : "watched by"
    active_tickets ||--o{ ticket_timers : "scheduled actions"
    user_notes }o--|| active_tickets : "linked via user_id"
```

## Transcript Viewer
A Streamlit web app for staff to view, filter, and manage ticket transcripts.

**Features:**
- Browse local transcript files or query database (PostgreSQL/MySQL)
- View embedded images and attachments
- Separate user vs. staff messages
- Hide/show internal staff notes with a toggle
- Staff authentication required

**Quick Start:**
```bash
export STREAMLIT_STAFF_PASSWORD="your_password"
streamlit run streamlit_transcripts.py
```

For full setup and configuration, see [TRANSCRIPT_VIEWER_README.md](TRANSCRIPT_VIEWER_README.md).

## Development
- Code style: follow existing project conventions.
- Tests: add unit tests for any new logic you add.
- Run the bot locally with the above steps. Use logging to debug behavior.

## Troubleshooting
- Bot not responding: ensure token is correct and bot is invited with correct scopes (bot + messages intents).
- Tickets not creating: verify category and guild IDs in config are correct and the bot has Manage Channels/Create Channel permissions.
- DM issues: users must allow DMs from server members or have direct messages enabled.

## Contributing
1. Fork the repository
2. Create a feature branch
3. Open a PR with a clear description and tests if applicable

## License
This project is licensed under the MIT License. See the LICENSE file for details.

## Contact
Maintainer: [VeeBuiltThat](https://github.com/VeeBuiltThat) — open an issue or PR for changes.

## Changelog
- v0.1 — Initial improved README and documentation
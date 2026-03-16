import mysql.connector
from mysql.connector import errorcode
import logging
from datetime import datetime
import os
import json

try:
    from config import DB_CONFIG
except Exception:
    DB_CONFIG = {
        "host": os.getenv("DB_HOST", "gameswaw5.bisecthosting.com"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "u1079393_bwVUJntzFf"),
        "password": os.getenv("DB_PASS", "XzaXNWotYim7AWlIeudHjSoO"),
        "database": os.getenv("DB_NAME", "s1079393_ModMail"),
    }

logger = logging.getLogger("modmail.db")

class DatabaseManager:
    def __init__(self, bot):
        self.bot = bot
        self._user_notes_ready = False
        self.conn = mysql.connector.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"]
        )

    def _new_cursor(self):
        return self.conn.cursor(dictionary=True, buffered=True)

    def _execute(self, query: str, params=None, *, commit: bool = False):
        cursor = self._new_cursor()
        try:
            if params is None:
                cursor.execute(query)
            else:
                cursor.execute(query, params)
            if commit:
                self.conn.commit()
        finally:
            cursor.close()

    def _fetchone(self, query: str, params=None):
        cursor = self._new_cursor()
        try:
            if params is None:
                cursor.execute(query)
            else:
                cursor.execute(query, params)
            return cursor.fetchone()
        finally:
            cursor.close()

    def _fetchall(self, query: str, params=None):
        cursor = self._new_cursor()
        try:
            if params is None:
                cursor.execute(query)
            else:
                cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            cursor.close()

    def setup(self):
        self._ensure_single_open_ticket_constraint()
        self._ensure_transcript_table()
        self._ensure_user_notes_table()
        logger.info("Database connection established.")

    def _ensure_transcript_table(self):
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_transcripts (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                channel_id BIGINT NOT NULL UNIQUE,
                guild_id BIGINT,
                guild_name VARCHAR(255),
                channel_name VARCHAR(255),
                category_name VARCHAR(255),
                owner_id BIGINT NULL,
                owner_name VARCHAR(255) NULL,
                opened_by VARCHAR(255) NULL,
                closed_by VARCHAR(255) NULL,
                opened_at DATETIME NULL,
                closed_at DATETIME NULL,
                open_reason LONGTEXT NULL,
                close_reason LONGTEXT NULL,
                message_count INT DEFAULT 0,
                transcript_json LONGTEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """,
            commit=True,
        )

    def _ensure_user_notes_table(self):
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS user_notes (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                note LONGTEXT NOT NULL,
                staff VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_notes_user_id_created_at (user_id, created_at)
            )
            """,
            commit=True,
        )
        self._user_notes_ready = True

    def _parse_iso_datetime(self, value):
        if not value or not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    def save_ticket_transcript(self, transcript_data: dict, closed_by: str = "System", close_reason: str = "Resolved"):
        ticket = transcript_data.get("ticket", {}) if isinstance(transcript_data, dict) else {}
        messages = transcript_data.get("messages", []) if isinstance(transcript_data, dict) else []

        channel_id = ticket.get("channel_id")
        if not channel_id:
            return False

        opened_at = None
        if messages:
            opened_at = self._parse_iso_datetime(messages[0].get("timestamp"))
        closed_at = self._parse_iso_datetime(ticket.get("closed_at"))

        open_reason = None
        opened_by = ticket.get("owner_name")
        for message in messages:
            if message.get("role") == "user" and (message.get("content") or "").strip():
                open_reason = (message.get("content") or "").strip()
                break

        transcript_json = json.dumps(transcript_data, ensure_ascii=False)

        self._execute(
            """
            INSERT INTO ticket_transcripts (
                channel_id, guild_id, guild_name, channel_name, category_name,
                owner_id, owner_name, opened_by, closed_by,
                opened_at, closed_at, open_reason, close_reason,
                message_count, transcript_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                guild_id = VALUES(guild_id),
                guild_name = VALUES(guild_name),
                channel_name = VALUES(channel_name),
                category_name = VALUES(category_name),
                owner_id = VALUES(owner_id),
                owner_name = VALUES(owner_name),
                opened_by = VALUES(opened_by),
                closed_by = VALUES(closed_by),
                opened_at = VALUES(opened_at),
                closed_at = VALUES(closed_at),
                open_reason = VALUES(open_reason),
                close_reason = VALUES(close_reason),
                message_count = VALUES(message_count),
                transcript_json = VALUES(transcript_json)
            """,
            (
                ticket.get("channel_id"),
                ticket.get("guild_id"),
                ticket.get("guild_name"),
                ticket.get("channel_name"),
                ticket.get("category"),
                ticket.get("owner_id"),
                ticket.get("owner_name"),
                opened_by,
                closed_by,
                opened_at,
                closed_at,
                open_reason,
                close_reason,
                len(messages),
                transcript_json,
            ),
            commit=True,
        )
        return True

    def _ensure_single_open_ticket_constraint(self):
        try:
            self._execute(
                """
                ALTER TABLE active_tickets
                ADD COLUMN open_ticket_user_id BIGINT
                GENERATED ALWAYS AS (
                    CASE WHEN status = 'open' THEN user_id ELSE NULL END
                ) STORED
                """,
                commit=True,
            )
            logger.info("Added generated column open_ticket_user_id to active_tickets.")
        except mysql.connector.Error as err:
            if err.errno != errorcode.ER_DUP_FIELDNAME:
                logger.warning(f"Could not add generated column open_ticket_user_id: {err}")

        try:
            self._execute(
                """
                CREATE UNIQUE INDEX uq_active_tickets_one_open_per_user
                ON active_tickets (open_ticket_user_id)
                """,
                commit=True,
            )
            logger.info("Created unique index uq_active_tickets_one_open_per_user.")
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_DUP_ENTRY:
                logger.warning(
                    "Cannot create unique open-ticket index because duplicate open tickets already exist. "
                    "Please close duplicate rows first, then restart to apply the constraint."
                )
            elif err.errno != errorcode.ER_DUP_KEYNAME:
                logger.warning(f"Could not create unique index uq_active_tickets_one_open_per_user: {err}")

    def get_open_ticket_channel_id(self, user_id: int, category_id: int = None):
        if category_id:
            result = self._fetchone(
                "SELECT channel_id FROM active_tickets WHERE user_id=%s AND category_id=%s AND status='open' LIMIT 1",
                (user_id, category_id)
            )
        else:
            result = self._fetchone(
                "SELECT channel_id FROM active_tickets WHERE user_id=%s AND status='open' LIMIT 1",
                (user_id,)
            )
        return int(result["channel_id"]) if result else None

    def create_ticket_entry(self, user, channel, category_id, ticket_type: str):
        existing_open_channel_id = self.get_open_ticket_channel_id(user.id)
        if existing_open_channel_id:
            return False

        try:
            self._execute(
                """
                INSERT INTO active_tickets 
                (channel_id, user_id, member_username, mod_username, category_id, channel_name, created_at, closed_at, status, ticket_type, mod_id)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), NULL, %s, %s, %s)
                """,
                (
                    channel.id,
                    user.id,
                    str(user),
                    None,
                    category_id,
                    channel.name,
                    "open",
                    ticket_type,
                    None
                ),
                commit=True,
            )
            return True
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_DUP_ENTRY:
                return False
            raise

    def close_ticket_by_user(self, user_id: int):
        self._execute(
            """
            UPDATE active_tickets 
            SET status='closed', closed_at=NOW() 
            WHERE user_id=%s AND status='open'
            """,
            (user_id,),
            commit=True,
        )

    def assign_mod_to_ticket(self, channel_id: int, mod_id: int, mod_username: str):
        self._execute(
            """
            UPDATE active_tickets
            SET mod_id = %s, mod_username = %s
            WHERE channel_id = %s AND status = 'open'
            """,
            (mod_id, mod_username, channel_id),
            commit=True,
        )

    def get_active_tickets(self):
        """Return all open tickets from the database."""
        return self._fetchall("SELECT * FROM active_tickets WHERE status = 'open'")

    def update_ticket_notified(self, channel_id: int):
        """Mark ticket as notified (after 48-hour reminder sent)."""
        # Add this column in your table if it doesn't exist yet:
        # ALTER TABLE active_tickets ADD COLUMN notified TINYINT(1) DEFAULT 0;
        self._execute(
            "UPDATE active_tickets SET notified = 1 WHERE channel_id = %s",
            (channel_id,),
            commit=True,
        )

    def get_ticket_by_channel(self, channel_id: int):
        return self._fetchone(
            "SELECT * FROM active_tickets WHERE channel_id=%s AND status='open' LIMIT 1",
            (channel_id,)
        )

    def close_ticket(self, channel_id: int, closed_at: datetime):
        self._execute(
            """
            UPDATE active_tickets
            SET status = 'closed',
                closed_at = %s
            WHERE channel_id = %s
            """,
            (closed_at, channel_id),
            commit=True,
        )

    def get_dx_response(self, key: str):
        row = self._fetchone("SELECT response FROM dx_responses WHERE `key`=%s LIMIT 1", (key,))
        if row:
            return row["response"]
        return None

    def add_dx_response(self, key: str, response: str):
        self._execute(
            "INSERT INTO dx_responses (`key`, `response`) VALUES (%s, %s)", (key, response), commit=True
        )

    def remove_dx_response(self, key: str):
        self._execute("DELETE FROM dx_responses WHERE `key`=%s", (key,), commit=True)

    def get_all_dx_responses(self):
        rows = self._fetchall("SELECT `key`, response FROM dx_responses")
        return [{"key": row["key"], "response": row["response"]} for row in rows]

    def add_ticket_timer(self, channel_id: int, user_id: int, action: str, execute_at: datetime):
        self._execute("""
            INSERT INTO ticket_timers (channel_id, user_id, action, execute_at)
            VALUES (%s, %s, %s, %s)
        """, (channel_id, user_id, action, execute_at), commit=True)

    def cancel_ticket_timer(self, channel_id: int, action: str):
        self._execute("""
            DELETE FROM ticket_timers
            WHERE channel_id=%s AND action=%s
        """, (channel_id, action), commit=True)

    # database_manager.py
    def get_pending_timers(self):
        return self._fetchall("SELECT * FROM ticket_timers WHERE status='pending'")



    def add_watcher(self, channel_id: int, mod_id: int):
        self._execute("""
            INSERT IGNORE INTO ticket_watchers (channel_id, mod_id)
            VALUES (%s, %s)
        """, (channel_id, mod_id), commit=True)

    def get_watchers(self, channel_id: int):
        rows = self._fetchall("SELECT mod_id FROM ticket_watchers WHERE channel_id=%s", (channel_id,))
        return [r["mod_id"] for r in rows]

    def remove_watcher(self, channel_id: int, mod_id: int):
        self._execute(
            "DELETE FROM ticket_watchers WHERE channel_id=%s AND mod_id=%s",
            (channel_id, mod_id),
            commit=True,
        )

    def add_note(self, user_id: int, note: str, staff: str):
        """Add a note for a user."""
        if not self._user_notes_ready:
            self._ensure_user_notes_table()
        try:
            self._execute(
                """
                INSERT INTO user_notes (user_id, note, staff, created_at)
                VALUES (%s, %s, %s, NOW())
                """,
                (user_id, note, staff),
                commit=True,
            )
        except mysql.connector.Error as err:
            if err.errno != errorcode.ER_NO_SUCH_TABLE:
                raise
            self._ensure_user_notes_table()
            self._execute(
                """
                INSERT INTO user_notes (user_id, note, staff, created_at)
                VALUES (%s, %s, %s, NOW())
                """,
                (user_id, note, staff),
                commit=True,
            )

    def get_notes(self, user_id: int):
        """Retrieve all notes for a user, ordered by creation time."""
        if not self._user_notes_ready:
            self._ensure_user_notes_table()
        try:
            return self._fetchall(
                """
                SELECT id, user_id, note, staff, created_at
                FROM user_notes
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,)
            )
        except mysql.connector.Error as err:
            if err.errno != errorcode.ER_NO_SUCH_TABLE:
                raise
            self._ensure_user_notes_table()
            return self._fetchall(
                """
                SELECT id, user_id, note, staff, created_at
                FROM user_notes
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,)
            )
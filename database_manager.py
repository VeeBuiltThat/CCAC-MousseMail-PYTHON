import mysql.connector
from mysql.connector import errorcode
import logging
from datetime import datetime
import os

try:
    from config import DB_CONFIG
except Exception:
    DB_CONFIG = {
        "host": os.getenv("DB_HOST", "gameswaw5.bisecthosting.com"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "u1079393_bwVUJntzFf"),
        "password": os.getenv("DB_PASS", ""),
        "database": os.getenv("DB_NAME", "s1079393_ModMail"),
    }

logger = logging.getLogger("modmail.db")

class DatabaseManager:
    def __init__(self, bot):
        self.bot = bot
        self.conn = mysql.connector.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"]
        )
        self.cursor = self.conn.cursor(dictionary=True)

    def setup(self):
        self._ensure_single_open_ticket_constraint()
        logger.info("Database connection established.")

    def _ensure_single_open_ticket_constraint(self):
        try:
            self.cursor.execute(
                """
                ALTER TABLE active_tickets
                ADD COLUMN open_ticket_user_id BIGINT
                GENERATED ALWAYS AS (
                    CASE WHEN status = 'open' THEN user_id ELSE NULL END
                ) STORED
                """
            )
            self.conn.commit()
            logger.info("Added generated column open_ticket_user_id to active_tickets.")
        except mysql.connector.Error as err:
            if err.errno != errorcode.ER_DUP_FIELDNAME:
                logger.warning(f"Could not add generated column open_ticket_user_id: {err}")

        try:
            self.cursor.execute(
                """
                CREATE UNIQUE INDEX uq_active_tickets_one_open_per_user
                ON active_tickets (open_ticket_user_id)
                """
            )
            self.conn.commit()
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
            self.cursor.execute(
                "SELECT channel_id FROM active_tickets WHERE user_id=%s AND category_id=%s AND status='open'",
                (user_id, category_id)
            )
        else:
            self.cursor.execute(
                "SELECT channel_id FROM active_tickets WHERE user_id=%s AND status='open'",
                (user_id,)
            )
        result = self.cursor.fetchone()
        return int(result["channel_id"]) if result else None

    def create_ticket_entry(self, user, channel, category_id, ticket_type: str):
        existing_open_channel_id = self.get_open_ticket_channel_id(user.id)
        if existing_open_channel_id:
            return False

        try:
            self.cursor.execute(
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
                )
            )
            self.conn.commit()
            return True
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_DUP_ENTRY:
                return False
            raise

    def close_ticket_by_user(self, user_id: int):
        self.cursor.execute(
            """
            UPDATE active_tickets 
            SET status='closed', closed_at=NOW() 
            WHERE user_id=%s AND status='open'
            """,
            (user_id,)
        )
        self.conn.commit()

    def assign_mod_to_ticket(self, channel_id: int, mod_id: int, mod_username: str):
        self.cursor.execute(
            """
            UPDATE active_tickets
            SET mod_id = %s, mod_username = %s
            WHERE channel_id = %s AND status = 'open'
            """,
            (mod_id, mod_username, channel_id)
        )
        self.conn.commit()
    def get_active_tickets(self):
        """Return all open tickets from the database."""
        self.cursor.execute("SELECT * FROM active_tickets WHERE status = 'open'")
        return self.cursor.fetchall()

    def update_ticket_notified(self, channel_id: int):
        """Mark ticket as notified (after 48-hour reminder sent)."""
        # Add this column in your table if it doesn't exist yet:
        # ALTER TABLE active_tickets ADD COLUMN notified TINYINT(1) DEFAULT 0;
        self.cursor.execute(
            "UPDATE active_tickets SET notified = 1 WHERE channel_id = %s",
            (channel_id,)
        )
        self.conn.commit()

    def get_ticket_by_channel(self, channel_id: int):
        self.cursor.execute(
            "SELECT * FROM active_tickets WHERE channel_id=%s AND status='open'",
            (channel_id,)
        )
        return self.cursor.fetchone()

    def close_ticket(self, channel_id: int, closed_at: datetime):
        self.cursor.execute(
            """
            UPDATE active_tickets
            SET status = 'closed',
                closed_at = %s
            WHERE channel_id = %s
            """,
            (closed_at, channel_id)
        )
        self.conn.commit()

    def get_dx_response(self, key: str):
        self.cursor.execute("SELECT response FROM dx_responses WHERE `key`=%s", (key,))
        row = self.cursor.fetchone()
        if row:
            return row["response"]
        return None

    def add_dx_response(self, key: str, response: str):
        self.cursor.execute(
            "INSERT INTO dx_responses (`key`, `response`) VALUES (%s, %s)", (key, response)
        )
        self.conn.commit()

    def remove_dx_response(self, key: str):
        self.cursor.execute("DELETE FROM dx_responses WHERE `key`=%s", (key,))
        self.conn.commit()

    def get_all_dx_responses(self):
        self.cursor.execute("SELECT `key`, response FROM dx_responses")
        rows = self.cursor.fetchall()
        return [{"key": row["key"], "response": row["response"]} for row in rows]

    def add_ticket_timer(self, channel_id: int, user_id: int, action: str, execute_at: datetime):
        self.cursor.execute("""
            INSERT INTO ticket_timers (channel_id, user_id, action, execute_at)
            VALUES (%s, %s, %s, %s)
        """, (channel_id, user_id, action, execute_at))
        self.conn.commit()

    def cancel_ticket_timer(self, channel_id: int, action: str):
        self.cursor.execute("""
            DELETE FROM ticket_timers
            WHERE channel_id=%s AND action=%s
        """, (channel_id, action))
        self.conn.commit()

    # database_manager.py
    def get_pending_timers(self):
        self.cursor.execute("SELECT * FROM ticket_timers WHERE status='pending'")
        return self.cursor.fetchall()



    def add_watcher(self, channel_id: int, mod_id: int):
        self.cursor.execute("""
            INSERT IGNORE INTO ticket_watchers (channel_id, mod_id)
            VALUES (%s, %s)
        """, (channel_id, mod_id))
        self.conn.commit()

    def get_watchers(self, channel_id: int):
        self.cursor.execute("SELECT mod_id FROM ticket_watchers WHERE channel_id=%s", (channel_id,))
        rows = self.cursor.fetchall()
        return [r["mod_id"] for r in rows]

    def remove_watcher(self, channel_id: int, mod_id: int):
        self.cursor.execute(
            "DELETE FROM ticket_watchers WHERE channel_id=%s AND mod_id=%s",
            (channel_id, mod_id)
        )
        self.conn.commit()

    def add_note(self, user_id: int, note: str, staff: str):
        """Add a note for a user."""
        self.cursor.execute(
            """
            INSERT INTO user_notes (user_id, note, staff, created_at)
            VALUES (%s, %s, %s, NOW())
            """,
            (user_id, note, staff)
        )
        self.conn.commit()

    def get_notes(self, user_id: int):
        """Retrieve all notes for a user, ordered by creation time."""
        self.cursor.execute(
            """
            SELECT id, user_id, note, staff, created_at
            FROM user_notes
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,)
        )
        return self.cursor.fetchall()
"""
Note manager - wraps database operations for user notes.
"""


class NoteManager:
    _default_bot = None

    def __init__(self, bot):
        self.bot = bot
        NoteManager._default_bot = bot

    @classmethod
    def _resolve_bot(cls, bot=None):
        resolved_bot = bot or cls._default_bot
        if resolved_bot is None:
            raise RuntimeError("NoteManager has no bot context. Initialize NoteManager(bot) first.")
        return resolved_bot

    @classmethod
    def add_note(cls, user_id: int, note: str, staff: str, bot=None):
        """Add a note for a user to the database."""
        resolved_bot = cls._resolve_bot(bot)
        resolved_bot.db.add_note(user_id, note, staff)

    @classmethod
    def get_notes(cls, user_id: int, bot=None):
        """Retrieve all notes for a user from the database."""
        resolved_bot = cls._resolve_bot(bot)
        return resolved_bot.db.get_notes(user_id)


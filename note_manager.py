"""
Note manager - wraps database operations for user notes.
"""


class NoteManager:
    def __init__(self, bot):
        self.bot = bot

    def add_note(self, user_id: int, note: str, staff: str):
        """Add a note for a user to the database."""
        self.bot.db.add_note(user_id, note, staff)

    def get_notes(self, user_id: int):
        """Retrieve all notes for a user from the database."""
        return self.bot.db.get_notes(user_id)


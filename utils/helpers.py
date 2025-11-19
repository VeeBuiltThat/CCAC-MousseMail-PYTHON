def log_message(message: str) -> None:
    """Logs a message to the console."""
    print(f"[LOG] {message}")

def format_embed(title: str, description: str, color: int) -> dict:
    """Creates a formatted embed dictionary for Discord messages."""
    return {
        "title": title,
        "description": description,
        "color": color
    }

def get_user_data(user_id: int) -> dict:
    """Retrieves user data from the database or cache."""
    # Placeholder for user data retrieval logic
    return {"id": user_id, "name": "User Name"}

def check_permissions(user, required_permissions: list) -> bool:
    """Checks if the user has the required permissions."""
    return all(perm in user.permissions for perm in required_permissions)

def format_ticket_message(ticket_id: int, user_name: str) -> str:
    """Formats a message for ticket notifications."""
    return f"Ticket #{ticket_id} created by {user_name}. Please check the ticket for details."
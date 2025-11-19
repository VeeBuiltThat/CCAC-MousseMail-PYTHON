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
- Development
- Troubleshooting
- Contributing
- License
- Contact

## Overview
Users can DM the bot to open a private ticket channel inside a configured category. Staff can reply, move tickets between categories, and use premade replies.

## Features
- Ticket creation via DM
- Private ticket channels in configured categories
- Staff-only commands to reply, edit replies, move tickets
- Pre-made replies (dx)
- Config-driven (server IDs, category IDs, bot token)

## Requirements
- Python 3.10+ recommended
- pip
- Discord bot token (from the Discord Developer Portal)

## Installation (Windows)
1. Clone the repo:
   ```
   git clone https://github.com/yourusername/Modmail-master.git
   cd Modmail-master
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
  "guild_id": 123456789012345678,
  "contact_category_id": 987654321098765432,
  "staff_role_id": 234567890123456789,
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
Maintainter: yourusername — open an issue or PR for changes.

## Changelog
- v0.1 — Initial improved README and documentation
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
import asyncio
import discord
from discord.ext import commands
from aiohttp import ClientSession
import logging
import threading
import traceback


from config_manager import ConfigManager
from thread_manager import ThreadManager
from database_manager import DatabaseManager
from dateutil.relativedelta import relativedelta
import config as app_config

GUILD_ID = getattr(app_config, "GUILD_ID", 0)
STAFF_ROLE_ID = getattr(app_config, "STAFF_ROLE_ID", 0)
CATEGORY_IDS = getattr(app_config, "CATEGORY_IDS", {})
TICKET_MESSAGES = getattr(app_config, "TICKET_MESSAGES", [])
TEMP_DIR = getattr(app_config, "TEMP_DIR", ".")
LOG_DIR = getattr(app_config, "LOG_DIR", "logs")
TICKET_REMINDER_HOURS = getattr(app_config, "TICKET_REMINDER_HOURS", 48)
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
ERROR_CHANNEL_ID = getattr(app_config, "ERROR_CHANNEL_ID", 1482074428606255154)

BOT_BUILD_MARKER = getattr(app_config, "BOT_BUILD_MARKER", "2026-03-04T14:58Z-note-fix-v3")

from note_manager import NoteManager


logger = logging.getLogger("modmail")
log_dir = os.path.join(TEMP_DIR, LOG_DIR)
os.makedirs(log_dir, exist_ok=True)


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()]
    )


def resolve_bot_token(config_manager=None):
    candidates = [
        getattr(app_config, "BOT_TOKEN", None),
        getattr(app_config, "DISCORD_TOKEN", None),
    ]

    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        cleaned = candidate.strip().strip('"').strip("'")
        if cleaned:
            return cleaned

    return None


HELP_COMMAND_OVERRIDES = {
    "r": {
        "summary": "Reply to the user tied to the current ticket.",
        "usage": "%r <message>",
        "example": "%r Thanks for the report. We're reviewing it now.",
        "group": "Messaging",
    },
    "re": {
        "summary": "Edit a previously sent staff reply by replying to the staff confirmation message.",
        "usage": "%re <new message>",
        "example": "%re Small update: this has now been resolved.",
        "group": "Messaging",
    },
    "anon": {
        "summary": "Send a reply without showing your staff identity.",
        "usage": "%anon <message>",
        "example": "%anon Please send the missing screenshot when ready.",
        "group": "Messaging",
    },
    "delete": {
        "summary": "Delete a DM previously sent to the user by replying to the matching staff log message.",
        "usage": "%delete",
        "example": "%delete",
        "group": "Messaging",
    },
    "dx": {
        "summary": "List all saved premade response keys.",
        "usage": "%dx",
        "example": "%dx",
        "group": "Messaging",
    },
    "dxadd": {
        "summary": "Save a new premade response under a key.",
        "usage": "%dxadd <key> <response>",
        "example": "%dxadd greet Hello, thanks for reaching out.",
        "group": "Messaging",
    },
    "msg": {
        "summary": "Preview a saved premade response in the current ticket.",
        "usage": "%msg <key>",
        "example": "%msg greet",
        "group": "Messaging",
    },
    "close": {
        "summary": "Close the current ticket immediately or after a delay.",
        "usage": "%close [time]",
        "example": "%close 1h30m",
        "group": "Ticket Flow",
    },
    "cancelclose": {
        "summary": "Cancel a scheduled ticket close.",
        "usage": "%cancelclose",
        "example": "%cancelclose",
        "group": "Ticket Flow",
    },
    "suspend": {
        "summary": "Suspend the current ticket and auto-close it after 24 hours if the user stays inactive.",
        "usage": "%suspend",
        "example": "%suspend",
        "group": "Ticket Flow",
    },
    "move": {
        "summary": "Move the current ticket to another configured category.",
        "usage": "%move <category>",
        "example": "%move reports",
        "group": "Ticket Flow",
    },
    "transfer": {
        "summary": "Transfer ownership of the current ticket to another staff member.",
        "usage": "%transfer <@staff>",
        "example": "%transfer @Moderator",
        "group": "Ticket Flow",
    },
    "contact": {
        "summary": "Open a new outbound contact ticket for a user.",
        "usage": "%contact <user_id> [reason]",
        "example": "%contact 123456789012345678 Follow-up on your application",
        "group": "Ticket Flow",
    },
    "notifyme": {
        "summary": "Subscribe yourself to user reply notifications for this ticket.",
        "usage": "%notifyme",
        "example": "%notifyme",
        "group": "Ticket Flow",
    },
    "transcript": {
        "summary": "Save or review ticket transcripts.",
        "usage": "%transcript [user_id]",
        "example": "%transcript 123456789012345678",
        "group": "Ticket Flow",
    },
    "note": {
        "summary": "Attach an internal note to the user tied to the current ticket.",
        "usage": "%note <message>",
        "example": "%note User was cooperative and provided proof quickly.",
        "group": "Staff Tools",
    },
    "trs": {
        "summary": "Review a user's stored transcripts and internal notes.",
        "usage": "%trs <user_id>",
        "example": "%trs 123456789012345678",
        "group": "Staff Tools",
    },
    "remindme": {
        "summary": "Send yourself a reminder after a delay.",
        "usage": "%remindme <about> <when>",
        "example": "%remindme check screenshots 2h",
        "group": "Staff Tools",
    },
    "raw": {
        "summary": "Show the raw user ID for the current ticket.",
        "usage": "%raw",
        "example": "%raw",
        "group": "Staff Tools",
    },
    "language": {
        "summary": "Placeholder for translation tooling.",
        "usage": "%language <code> [text]",
        "example": "%language nl Hello there",
        "group": "Staff Tools",
    },
    "stats": {
        "summary": "Show ticket activity stats for authorized staff.",
        "usage": "%stats",
        "example": "%stats",
        "group": "Staff Tools",
    },
    "create": {
        "summary": "Create a new Discord category if you have the required role or permission.",
        "usage": "%create <category name>",
        "example": "%create Event Queue",
        "group": "Admin",
    },
    "help": {
        "summary": "Show the command guide or inspect a single command.",
        "usage": "%help [command]",
        "example": "%help close",
        "group": "General",
    },
}

HELP_CATEGORY_ORDER = ["General", "Messaging", "Ticket Flow", "Staff Tools", "Admin", "Other"]


class ModmailBot(commands.Bot):
    def __init__(self):
        self.config = ConfigManager(self)
        self.config.populate_cache()
        self.confirmed_users = set()

        intents = discord.Intents.default()
        intents.messages = True
        intents.guilds = True
        intents.members = True
        intents.dm_messages = True
        intents.message_content = True

        super().__init__(command_prefix="%", intents=intents, help_command=None)

        self.session = None
        self.loaded_cogs = [
            "cogs.staff_commands",
            "cogs.category_management",
            "cogs.modmail"
        ]
        self._extensions_loaded = False
        self._connected = asyncio.Event()

        self.guild_id = GUILD_ID
        self.threads = ThreadManager(self)
        self.db = DatabaseManager(self)
        self.note_manager = NoteManager(self)

        self.log_file_path = os.path.join(TEMP_DIR, LOG_DIR, "modmail.log")
        configure_logging()
        self.add_command(self._build_help_command())

    def _command_meta(self, command: commands.Command):
        return HELP_COMMAND_OVERRIDES.get(command.name, {})

    def _command_summary(self, command: commands.Command):
        meta = self._command_meta(command)
        summary = meta.get("summary") or command.short_doc or command.help or "No description available."
        return summary.splitlines()[0].strip()

    def _command_group(self, command: commands.Command):
        meta = self._command_meta(command)
        cog_name = getattr(command.cog, "qualified_name", None)
        return meta.get("group") or cog_name or "Other"

    def _build_help_embed(self, title: str, description: str, color: discord.Color):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Use %help <command> for details.")
        return embed

    async def _send_help_overview(self, ctx: commands.Context):
        commands_list = sorted(self.commands, key=lambda command: command.name)
        grouped_commands = {group_name: [] for group_name in HELP_CATEGORY_ORDER}

        for command in commands_list:
            if command.hidden:
                continue
            group_name = self._command_group(command)
            if group_name not in grouped_commands:
                grouped_commands[group_name] = []
            grouped_commands[group_name].append(command)

        embed = self._build_help_embed(
            title="Help Center",
            description="A quick reference for staff commands.",
            color=discord.Color.blurple()
        )

        ordered_groups = HELP_CATEGORY_ORDER + [name for name in grouped_commands if name not in HELP_CATEGORY_ORDER]
        for group_name in ordered_groups:
            group_commands = grouped_commands.get(group_name, [])
            if not group_commands:
                continue

            lines = []
            current_length = 0
            for command in group_commands:
                line = f"`%{command.name}` - {self._command_summary(command)}"
                if current_length + len(line) + 1 > 1024:
                    break
                lines.append(line)
                current_length += len(line) + 1

            embed.add_field(name=group_name, value="\n".join(lines), inline=False)

        await ctx.send(embed=embed)

    async def _send_help_for_command(self, ctx: commands.Context, command_name: str):
        command = self.get_command(command_name)
        if command is None or command.hidden:
            await ctx.send(embed=self._build_help_embed(
                title="Help Error",
                description=f"No command named `{command_name}` was found.",
                color=discord.Color.red()
            ))
            return

        meta = self._command_meta(command)
        usage = meta.get("usage") or f"%{command.qualified_name}"
        example = meta.get("example")
        summary = self._command_summary(command)

        embed = self._build_help_embed(
            title=f"Command: %{command.name}",
            description=summary,
            color=discord.Color.green()
        )
        embed.add_field(name="Usage", value=f"`{usage}`", inline=False)
        embed.add_field(name="Category", value=self._command_group(command), inline=True)

        aliases = command.aliases or []
        embed.add_field(
            name="Aliases",
            value=", ".join(f"`{alias}`" for alias in aliases) if aliases else "None",
            inline=True
        )

        if example:
            embed.add_field(name="Example", value=f"`{example}`", inline=False)

        if command.help and command.help.strip() and command.help.strip() != summary:
            embed.add_field(name="Details", value=command.help.strip()[:1024], inline=False)

        await ctx.send(embed=embed)

    def _build_help_command(self):
        @commands.command(name="help")
        async def help_command(ctx: commands.Context, *, command_name: str = None):
            if command_name:
                await self._send_help_for_command(ctx, command_name.strip().lower())
                return
            await self._send_help_overview(ctx)

        return help_command

    async def on_ready(self):
        logger.info(f"Bot ready as {self.user} (ID: {self.user.id})")
        logger.info(f"Build marker: {BOT_BUILD_MARKER} | file={__file__}")
        if not self._extensions_loaded:
            await self.load_extensions()
            self._extensions_loaded = True
        self.loop.create_task(self.timer_task())
        self._connected.set()

    async def _resolve_error_channel(self):
        if not ERROR_CHANNEL_ID:
            return None
        channel = self.get_channel(ERROR_CHANNEL_ID)
        if channel is not None:
            return channel
        try:
            return await self.fetch_channel(ERROR_CHANNEL_ID)
        except Exception:
            return None

    async def _send_error_report(self, title: str, context: str, details: str):
        channel = await self._resolve_error_channel()
        if channel is None:
            return

        # Discord embed descriptions are capped at 4096 chars.
        max_len = 3900
        if not details:
            details = "No traceback available."
        chunks = [details[i:i + max_len] for i in range(0, len(details), max_len)]

        for index, chunk in enumerate(chunks[:3], start=1):
            suffix = f" (part {index}/{len(chunks)})" if len(chunks) > 1 else ""
            embed = discord.Embed(
                title=f"{title}{suffix}",
                description=f"{context}\n\n```{chunk}```",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            await channel.send(embed=embed)

    async def on_error(self, event, *args, **kwargs):
        """Log unhandled event errors and notify staff error channel."""
        err_text = traceback.format_exc()
        logger.error(f"Error in {event}: {err_text}")
        try:
            await self._send_error_report("⚠️ Error Detected", f"Event: {event}", err_text)
        except Exception:
            pass

    async def on_command_error(self, ctx, error):
        """Report unhandled command errors to the staff error channel."""
        if hasattr(ctx.command, "on_error"):
            return
        if isinstance(error, commands.CommandNotFound):
            return

        original = getattr(error, "original", error)
        tb_text = "".join(traceback.format_exception(type(original), original, original.__traceback__))
        logger.error("Command error in %s by %s: %s", getattr(ctx.command, "qualified_name", "unknown"), ctx.author, tb_text)

        context = (
            f"Command: {getattr(ctx.command, 'qualified_name', 'unknown')}\n"
            f"Author: {ctx.author} ({ctx.author.id})\n"
            f"Channel: {ctx.channel} ({ctx.channel.id})"
        )
        try:
            await self._send_error_report("⚠️ Command Error", context, tb_text)
        except Exception:
            pass

    async def timer_task(self):
        """Periodic task that checks ticket timers (24h suspend closures)."""
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                now = datetime.now(timezone.utc)

                # === Handle 24-hour suspended ticket closures ===
                pending_timers = self.db.get_pending_timers()
                for timer_entry in pending_timers:
                    try:
                        execute_at = timer_entry["execute_at"]
                        if isinstance(execute_at, str):
                            execute_at = datetime.strptime(execute_at, "%Y-%m-%d %H:%M:%S")
                        execute_at = execute_at.replace(tzinfo=timezone.utc)

                        if now >= execute_at:
                            channel = self.get_channel(int(timer_entry["channel_id"]))
                            action = timer_entry["action"]

                            if action in ("close", "suspend"):
                                if action == "suspend":
                                    embed = discord.Embed(
                                        title="📨 Ticket Closed",
                                        description="User did not respond. This suspended ticket has been closed automatically.",
                                        color=discord.Color.red()
                                    )
                                    if channel:
                                        await channel.send(embed=embed)

                                if channel:
                                    await self.close_ticket_now(channel)

                            # Remove timer from database
                            self.db.cancel_ticket_timer(timer_entry["channel_id"], action)

                    except Exception as e:
                        logger.error(f"Error while processing timer entry {timer_entry}: {e}")
                        try:
                            await self._send_error_report(
                                "⚠️ Timer Processing Error",
                                f"Timer entry channel_id={timer_entry.get('channel_id')} action={timer_entry.get('action')}",
                                traceback.format_exc()
                            )
                        except Exception:
                            pass

            except Exception as e:
                logger.error(f"Error in timer_task loop: {e}")
                try:
                    await self._send_error_report(
                        "⚠️ Timer Loop Error",
                        "Unhandled exception in timer_task loop",
                        traceback.format_exc()
                    )
                except Exception:
                    pass

            # Run every 5 minutes
            await asyncio.sleep(300)



    
    async def close_ticket_now(self, channel):
        self.db.close_ticket(channel.id, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        await channel.delete()

    async def load_extensions(self):
        for cog in self.loaded_cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded extension: {cog}")
            except Exception as e:
                logger.error(f"Failed to load extension {cog}: {e}")

    def build_embed(self, title, description, color, author=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        if author:
            embed.set_author(name=str(author), icon_url=author.display_avatar.url)
        return embed

    # <<< ADD THIS METHOD HERE >>>
    async def get_user_info_embed(self, user: discord.User):
        guild = self.get_guild(GUILD_ID)
        member = guild.get_member(user.id) if guild else None

        # Username | ID
        username_line = f"**Username | ID:** {user} | {user.id}"

        # Account age
        now = datetime.now(timezone.utc)
        delta = relativedelta(now, user.created_at)
        account_age_line = (
            f"**Account age:** {delta.years}y - {delta.months}m - "
            f"{delta.days}d - {delta.hours}h"
        )

        # Roles from specific server
        roles_line = "**Roles:** "
        if member:
            role_names = [r.name for r in member.roles if r.name != "@everyone"]
            roles_line += ", ".join(role_names) if role_names else "No roles"
        else:
            roles_line += "Not in server"

        embed = discord.Embed(
            title="User Information",
            color=discord.Color.blue()
        )
        embed.add_field(name="User", value=username_line, inline=False)
        embed.add_field(name="Account Age", value=account_age_line, inline=False)
        embed.add_field(name="Roles", value=roles_line, inline=False)

        return embed

    def find_open_ticket_channel_for_user(self, user_id: int, guild: discord.Guild = None):
        if guild is None:
            guild = self.get_guild(self.guild_id)
        if guild is None:
            return None

        allowed_category_ids = set(CATEGORY_IDS.values())
        user_id_marker = f"({user_id})"

        for channel in guild.text_channels:
            if channel.category_id not in allowed_category_ids:
                continue
            if channel.topic and user_id_marker in channel.topic:
                return channel

        return None

    async def on_message(self, message):
        if message.author.bot:
            return

        if isinstance(message.channel, discord.DMChannel):
            await self.handle_user_dm(message)

        await self.process_commands(message)

    async def handle_user_dm(self, message: discord.Message):
        user = message.author
        channel_id = self.db.get_open_ticket_channel_id(user.id)
        channel = None

        if channel_id:
            channel = self.get_channel(channel_id)

        if channel is None:
            fallback_channel = self.find_open_ticket_channel_for_user(user.id)
            if fallback_channel is not None:
                channel = fallback_channel
                channel_id = fallback_channel.id

        if channel_id:
            if channel is None:
                self.db.close_ticket(channel_id, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
                self.confirmed_users.discard(user.id)
            else:
                self.db.cancel_ticket_timer(channel_id, "suspend")

                watchers = self.db.get_watchers(channel_id)
                mentions = [self.get_user(w).mention for w in set(watchers) if self.get_user(w)]

                if mentions:
                    await channel.send(f"{' '.join(mentions)}")

                embed = self.build_embed(
                    title="User Message",
                    description=f"\n{message.content if message.content else ''}",
                    color=discord.Color.blue(),
                    author=user
                )

                if message.attachments:
                    first_attachment = message.attachments[0]
                    if first_attachment.content_type and first_attachment.content_type.startswith("image/"):
                        embed.set_image(url=first_attachment.url)

                await channel.send(embed=embed)

                if len(message.attachments) > 1:
                    files = []
                    for attachment in message.attachments[1:]:
                        try:
                            fp = await attachment.to_file()
                            files.append(fp)
                        except Exception as e:
                            logger.warning(f"Failed to forward attachment: {e}")
                    if files:
                        await channel.send(content="Additional attachments:", files=files)

                return

        # No open ticket → send welcome menu
        welcome_embed = self.build_embed(
            title="🎟️ Contact Staff!",
            description=(
                "**Please select the reason for your ticket below:**\n\n"
                "📌 **Reporting a User** – Rule-breaking reports\n"
                "☕ **ACGGOODS** – Questions about perks for ACGgoods\n"
                "💡 **Suggestions** – Event ideas or server improvement\n"
                "📝 **Appeals** – Appeal a warning\n"
                "🛠️ **Technical Issues** – Channel\reaction issues (not device support)\n"
                "❓ **General Questions** – Ask about server/partnerships\n"
                "🛟 **Emergancy Commissions** – Need help? Apply for emergancy commissions!\n"
                "🎉 **Events & Giveaways** – Won an event? Want to offer a prize? Or maybe you want to host a giveaway? Open a ticket!\n"
                "🍰 **Cheesecake Reminder:**\n\n"
                "Please do **not spam** staff. Have all necessary materials ready before submitting.\n"
                "Thank you!"
            ),
            color=discord.Color.pink()
        )
        welcome_embed.set_image(
            url="https://media.discordapp.net/attachments/1329869584190406780/1351717260145852458/IMG_5552.png"
        )
        await message.channel.send(embed=welcome_embed, view=TicketCategoryView())

    async def on_guild_channel_delete(self, channel):
        if channel.topic:
            try:
                user_id_str = channel.topic.split("(")[-1].rstrip(")")
                user_id = int(user_id_str)

                channel_id = self.db.get_open_ticket_channel_id(user_id)
                if channel_id == channel.id:
                    self.db.close_ticket(channel.id, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
                    self.confirmed_users.discard(user_id)
                    logger.info(f"Removed ticket for user {user_id} due to channel deletion.")
            except Exception as e:
                logger.warning(f"Failed to parse user ID from channel topic: {e}")

    def run(self):
        async def runner():
            async with self:
                self.session = ClientSession()
                self.db.setup()
                token = resolve_bot_token(self.config)
                if not token:
                    logger.error("Bot token is missing. Set BOT_TOKEN or DISCORD_TOKEN in config/env.")
                    return
                await self.start(token)

        asyncio.run(runner())


# --- UI Components ---

class TicketCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="📩 Contact Staff", value="contact"),
            discord.SelectOption(label="🛒 ACGgoods", value="acggoods"),
            discord.SelectOption(label="✅ Trusted Seller/Buyer", value="trusted"),
            discord.SelectOption(label="❓ General Questions", value="questions"),
            discord.SelectOption(label="💡 Suggestions", value="suggestions"),
            discord.SelectOption(label="🤝 Partnerships", value="partnerships"),
            discord.SelectOption(label="🚨 Reports", value="reports"),
            discord.SelectOption(label="🛑 Appeals", value="appeals"),
            discord.SelectOption(label="☕ Ko-Fi Help", value="ko-fi"),
            discord.SelectOption(label="🔞 NSFW Access", value="nsfw"),
            discord.SelectOption(label="🛟 Emergency Commissions", value="emergency"),
            discord.SelectOption(label="🎉 Events & Giveaways", value="events"),
        ]
        super().__init__(placeholder="📌 Select a ticket category...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        try:
            bot: ModmailBot = interaction.client
            user = interaction.user
            guild = interaction.guild or bot.get_guild(GUILD_ID)

            # ✅ Check if user already has an open ticket
            existing_channel_id = bot.db.get_open_ticket_channel_id(user.id)
            existing_channel = bot.get_channel(existing_channel_id) if existing_channel_id else None
            fallback_channel = bot.find_open_ticket_channel_for_user(user.id, guild=guild)

            if existing_channel or fallback_channel:
                await interaction.response.send_message(
                    "⚠️ You already have an open ticket. You cannot open another one.",
                    ephemeral=True
                )
                # Disable the dropdown for this user
                self.disabled = True
                await interaction.message.edit(view=self.view)
                return

            # Disable the dropdown after selection
            self.disabled = True
            await interaction.message.edit(view=self.view)

            # Proceed to send category details and open the ticket
            await send_category_details(interaction, self.values[0])
        except Exception:
            logger.exception("TicketCategorySelect callback failed")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "⚠️ Something went wrong while opening your ticket. Please try again.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "⚠️ Something went wrong while opening your ticket. Please try again.",
                        ephemeral=True
                    )
            except Exception:
                pass


class TicketCategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        logger.exception("TicketCategoryView on_error triggered: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "⚠️ Something went wrong while opening your ticket. Please try again.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "⚠️ Something went wrong while opening your ticket. Please try again.",
                    ephemeral=True
                )
        except Exception:
            pass


class ClaimTicketButton(discord.ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success)
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot: ModmailBot = interaction.client
        mod = interaction.user

        # Assign mod in DB
        bot.db.assign_mod_to_ticket(self.channel_id, mod.id, mod.name)
        bot.db.cancel_ticket_timer(self.channel_id, "unclaimed")

        # Ephemeral confirmation to mod
        await interaction.response.send_message(
            f"✅ {mod.mention} has claimed this ticket.", ephemeral=True
        )

        # Notify channel
        await interaction.followup.send(
            embed=discord.Embed(
                description=f"Ticket claimed by {mod.mention}.",
                color=discord.Color.orange()
            )
        )

        # Disable the button
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)



async def send_category_details(interaction: discord.Interaction, category_key: str):
    try:
        await _send_category_details(interaction, category_key)
    except Exception:
        logger.exception("send_category_details failed")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "⚠️ Something went wrong while opening your ticket. Please try again.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "⚠️ Something went wrong while opening your ticket. Please try again.",
                    ephemeral=True
                )
        except Exception:
            pass


async def _send_category_details(interaction: discord.Interaction, category_key: str):
    bot: ModmailBot = interaction.client
    user = interaction.user
    guild = interaction.guild
    if guild is None:
        guild = bot.get_guild(GUILD_ID)
        
    if guild is None:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Error",
                description="⚠️ Could not identify the server. Please try again later.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return

    existing_channel_id = bot.db.get_open_ticket_channel_id(user.id)
    existing_channel = bot.get_channel(existing_channel_id) if existing_channel_id else None
    fallback_channel = bot.find_open_ticket_channel_for_user(user.id, guild=guild)
    if existing_channel or fallback_channel:
        if interaction.response.is_done():
            await interaction.followup.send(
                "⚠️ You already have an open ticket. You cannot open another one.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "⚠️ You already have an open ticket. You cannot open another one.",
                ephemeral=True
            )
        return

    category_id = CATEGORY_IDS.get(category_key)
    if not category_id:
        await interaction.followup.send(
            "⚠️ That ticket category is not configured. Please contact staff.",
            ephemeral=True
        )
        return

    details_map = {
        "contact": (
            "**📞 Contact Staff!**\n"
            "Please select the reason for your ticket:\n\n"
            "**Reporting a User** Report rule-breaking behavior.\n"
            "**Technical Issues** Report server-related bugs (not device support).\n"
            "⏳ Please don’t ping staff. Have your materials ready and wait patiently!"
        ),
        "acggoods": (
            "**🛒 ACGgoods**\n"
            "Apply to gain the invite code\n"
            "Ask questions for ACGgoods"
        ),
        "trusted": (
            "**💼 Trusted Buyer/Seller Requirements**\n\n"
            "**Trusted Buyer:**\n"
            "- 5+ commission proofs\n"
            "- PayPal/Discord Nitro payments\n"
            "- Level 5+ role\n\n"
            "**Trusted Seller:**\n"
            "- 3+ commission proofs\n"
            "- PayPal/Ko-Fi/VGen/Discord Nitro payments\n"
            "- Level 5+ role"
        ),
        "questions": "**❓ General Questions**\nAsk about roles, events, or server features!",
        "suggestions": "**💡 Suggestions**\nShare your ideas to improve the server!",
        "partnerships": (
            "**🤝 Partnership Applications**\n"
            "- 1,500+ members\n"
            "- 6+ months old\n"
            "- Art-focused community\n"
            "- NSFW content must be age-gated"
        ),
        "reports": (
            "**🚨 Report a User**\n"
            "Only serious reports (scam, stolen art, repeat offenses).\n"
            "🔒 Confidential handling."
        ),
        "appeals": "**📜 Appeals**\nRespectful, clear appeals only.",
        "ko-fi": "**☕ Ko-Fi Help**\nAsk about perks or Ko-Fi Club!",
        "nsfw": (
            "**🔞 NSFW Access Verification**\n"
            "Verify 18+ with ID + username note.\n"
            "Sensitive info can be hidden."
        ),
        "emergency": (
            "**🛟 Emergency Commissions - Qualified Emergencies:**\n"
            "Bills necessary for life & schooling (rent, electric, water, wifi, phone, etc)\n"
            "Medical bills (including human & vet bills along with medication)\n"
            "Natural disaster impact relief\n"
            "Food / groceries\n"
            "Transportation to work / school / doctor (gas or bus fare)\n"
            "Funeral / cremation services\n"
            "**It is ultimately up to staff discretion whether or not your emergency will be accepted.**"
        ),
        "events": (
            "**🎉 Events & Giveaways**\n"
            "Won an event? Contact us!\n"
            "Want to offer a prize? Let us know!\n"
            "Want to host a giveaway? We can help!"
        ),
    }

    embed = discord.Embed(
        title="Mousse's Category Info",
        description=details_map.get(category_key, "Oopsie! Mousse doesn’t know this flavor."),
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed)

    # ✅ Create ticket channel
    discord_category = guild.get_channel(category_id)
    if not isinstance(discord_category, discord.CategoryChannel):
        return

    ticket_channel = await guild.create_text_channel(
        name=f"dx-{user.name}",
        category=discord_category,
        topic=f"Ticket for {user.name} ({user.id})"
    )

    created = bot.db.create_ticket_entry(user, ticket_channel, category_id, category_key)
    if not created:
        await interaction.followup.send(
            "⚠️ You already have an open ticket. You cannot open another one.",
            ephemeral=True
        )
        try:
            await ticket_channel.delete()
        except Exception as e:
            logger.warning(f"Failed to delete duplicate ticket channel {ticket_channel.id}: {e}")
        return

    # --- CREATE USER INFO EMBED AND SEND IT ---
    user_info_embed = await bot.get_user_info_embed(user)
    await ticket_channel.send(embed=user_info_embed)
    # ------------------------------------------------

    # send any existing staff notes for this user
    try:
        notes = bot.note_manager.get_notes(user.id)
    except Exception as e:
        logger.error(f"Failed to fetch notes for user {user.id}: {e}")
        notes = []
    if notes:
        note_text = "\n".join(
            f"[{n.get('created_at', n.get('timestamp', 'Unknown'))}] {n.get('staff', 'Unknown')}: {n.get('note', '')}"
            for n in notes
        )
        await ticket_channel.send(
            embed=discord.Embed(
                title="Staff Notes",
                description=note_text,
                color=discord.Color.dark_gold()
            )
        )

    # 🕒 Schedule first reminder 48h later
    execute_at = datetime.now(timezone.utc) + timedelta(hours=TICKET_REMINDER_HOURS)
    bot.db.add_ticket_timer(
        ticket_channel.id, user.id, "unclaimed", execute_at.strftime("%Y-%m-%d %H:%M:%S")
    )

    role_id = STAFF_ROLE_ID
    role_ping = f"<@&{role_id}>"

    staff_embed = discord.Embed(
        description="A new ticket has been created.\nClick **Claim Ticket** below to take responsibility.",
        color=discord.Color.blurple()
    )

    await ticket_channel.send(
        content=f"{role_ping}\nNew ticket from {user.mention} (ID: {user.id}) - Category: `{category_key}`",
        embed=staff_embed,
        view=ClaimTicketButton(ticket_channel.id),
        allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False)
    )

    try:
        await user.send(
            embed=discord.Embed(
                title="Ticket Created",
                description="Your ticket has been opened. Please describe your issue or request here.\n A staff member will be with you shortly, however response times may vary based on volume.",
                color=discord.Color.green()
            )
        )
    except discord.Forbidden:
        pass



if __name__ == "__main__":
    bot = ModmailBot()
    bot.run()

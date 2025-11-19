from datetime import datetime, timedelta, timezone
import os
import asyncio
import random
import discord
from discord.ext import commands
from aiohttp import ClientSession
import logging
import threading


from config_manager import ConfigManager
from thread_manager import ThreadManager
from database_manager import DatabaseManager
from dateutil.relativedelta import relativedelta
from config import GUILD_ID, STAFF_ROLE_ID, CATEGORY_IDS, TICKET_MESSAGES, TEMP_DIR, LOG_DIR, TICKET_REMINDER_HOURS, DISCORD_TOKEN


logger = logging.getLogger("modmail")
log_dir = os.path.join(TEMP_DIR, LOG_DIR)
os.makedirs(log_dir, exist_ok=True)


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()]
    )

temp_dir = "."


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

        super().__init__(command_prefix="%", intents=intents)

        self.session = None
        self.loaded_cogs = [
            "cogs.staff_commands",
            "cogs.category_management",
            "cogs.modmail"
        ]
        self._connected = asyncio.Event()

        self.guild_id = GUILD_ID
        self.threads = ThreadManager(self)
        self.db = DatabaseManager(self)

        log_dir = os.path.join(temp_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        self.log_file_path = os.path.join(log_dir, "modmail.log")
        configure_logging()

    async def on_ready(self):
        logger.info(f"Bot ready as {self.user} (ID: {self.user.id})")
        await self.load_extensions()
        self.loop.create_task(self.timer_task())
        self._connected.set()

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

            except Exception as e:
                logger.error(f"Error in timer_task loop: {e}")

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

    async def on_message(self, message):
        if message.author.bot:
            return

        if isinstance(message.channel, discord.DMChannel):
            await self.handle_user_dm(message)

        await self.process_commands(message)

    async def handle_user_dm(self, message: discord.Message):
        user = message.author
        channel_id = self.db.get_open_ticket_channel_id(user.id)

        if channel_id:
            channel = self.get_channel(channel_id)

            if channel is None:
                await self.db.close_ticket(channel_id, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
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
                    await self.db.close_ticket(user_id, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
                    self.confirmed_users.discard(user_id)
                    logger.info(f"Removed ticket for user {user_id} due to channel deletion.")
            except Exception as e:
                logger.warning(f"Failed to parse user ID from channel topic: {e}")

    def run(self):
        async def runner():
            async with self:
                self.session = ClientSession()
                self.db.setup()
                await self.start(DISCORD_TOKEN)

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
        bot: ModmailBot = interaction.client
        user = interaction.user

        # ✅ Check if user already has an open ticket
        existing_channel_id = bot.db.get_open_ticket_channel_id(user.id)
        if existing_channel_id:
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


class TicketCategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())


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

    category_id = CATEGORY_IDS.get(category_key)

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

    # --- CREATE USER INFO EMBED AND SEND IT ---
    user_info_embed = await bot.get_user_info_embed(user)
    await ticket_channel.send(embed=user_info_embed)
    # ------------------------------------------------

    bot.db.create_ticket_entry(user, ticket_channel, category_id, category_key)

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



def run_web_server():
    from web_server import app
    app.run(port=5000)

if __name__ == "__main__":
    # Start Flask server in a separate thread
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    bot = ModmailBot()
    bot.run()
    
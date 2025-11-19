import discord
from discord.ext import commands
import asyncio
import io
import re
import logging
from datetime import datetime, timedelta, timezone
import os
import aiohttp
from config import (
    JUNIOR_MOD_ROLE_ID, ADDITIONAL_STAFF_ROLE_ID, NSFW_CATEGORY_ID, 
    TICKET_CATEGORY_IDS, GUILD_ID, CATEGORY_ID, LOG_CHANNEL_ID,
    TRANSCRIPT_DIR, IMAGE_DIR
)

logger = logging.getLogger(__name__)

class Modmail(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = GUILD_ID
        self.category_id = CATEGORY_ID
        self.log_channel_id = LOG_CHANNEL_ID

        self.ticket_category_ids = TICKET_CATEGORY_IDS

        # ensure directories exist
        os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
        os.makedirs(IMAGE_DIR, exist_ok=True)
    """
    Modmail cog with robust scheduling + DB compatibility.

    Database expectations (bot.db):
      - add_ticket_timer(channel_id, user_id, action, execute_at)  # execute_at as 'YYYY-MM-DD HH:MM:SS' (preferred) or int timestamp (fallback)
      - cancel_ticket_timer(channel_id, action)
      - close_ticket(channel_id, closed_at)  # closed_at as 'YYYY-MM-DD HH:MM:SS' (preferred) or int timestamp (fallback)
      - add_watcher(channel_id, user_id)
    """
    
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = 1346839676333461625
        self.category_id = 1386412081246200000
        self.log_channel_id = 1352669054346854502

        # in-memory state (non-persistent)
        self.open_tickets = {}         # { user_id: channel_id }
        self.delayed_closures = {}     # { channel_id: asyncio.Task }
        self.suspended_tickets = {}    # { channel_id: task_or_flag }
        self.notify_watchers = {}      # { channel_id: [user_ids...] }

        self.ticket_category_ids = {
            1346881466881146910,  # contact
            1346882153279000648,  # trusted
            1402347454438838443,  # questions
            1402347609460576367,  # suggestions
            1402347709976936591,  # partnerships
            1402347829409874032,  # reports
            1402347868756643900,  # appeals
            1402348823598203061,  # ko-fi
            1346881386510024745,  # nsfw
            1346882435400466495,   # tech
            1419606665891811469, # emergancy
            1419606732971180104, # events
            1419606799438319660 # jrmod
        }

    
    # ---------------- Helpers ----------------

    def _get_user_id_from_topic(self, topic: str):
        """Extract Discord snowflake in parentheses, e.g. '... (123456789012345678)'"""
        if not topic:
            return None
        m = re.search(r"\((\d{17,20})\)", topic)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
        return None

    def _parse_time_to_seconds(self, timestr: str) -> int:
        """
        Parse times like:
        - "1:30" (hours:minutes) or "1:30:00" (h:m:s)
        - "90m", "1h30m", "3600s"
        - "15" (minutes)
        Returns seconds (int) or raises ValueError.
        """
        if not timestr:
            raise ValueError("Empty time string")
        s = timestr.strip().lower()

        if ":" in s:  # hh:mm or hh:mm:ss
            parts = s.split(":")
            if len(parts) == 2:
                h, m = map(int, parts)
                return h * 3600 + m * 60
            elif len(parts) == 3:
                h, m, sec = map(int, parts)
                return h * 3600 + m * 60 + sec
            else:
                raise ValueError("Invalid colon time format")

        tokens = re.findall(r"(\d+(?:\.\d+)?)([hms]?)", s)
        if tokens:
            total = 0
            for num, unit in tokens:
                num_val = float(num)
                if unit == "h":
                    total += int(num_val * 3600)
                elif unit == "m" or unit == "":
                    total += int(num_val * 60)
                elif unit == "s":
                    total += int(num_val)
            return total

        # treat plain number as minutes
        return int(float(s) * 60)

    def _format_dt_for_db(self, dt: datetime) -> str:
        """Return string in MySQL DATETIME format (UTC)."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    async def _try_db_add_ticket_timer(self, channel_id, user_id, action, execute_at_dt: datetime):
        """
        Try to call bot.db.add_ticket_timer with DATETIME string first, then fallback to timestamp if it errors.
        Returns True if DB call succeeded, False otherwise.
        """
        if not hasattr(self.bot, "db") or not hasattr(self.bot.db, "add_ticket_timer"):
            return False

        dt_str = self._format_dt_for_db(execute_at_dt)
        try:
            self.bot.db.add_ticket_timer(channel_id, user_id, action, dt_str)
            return True
        except TypeError:
            # maybe DB expects unix timestamp int
            try:
                self.bot.db.add_ticket_timer(channel_id, user_id, action, int(execute_at_dt.timestamp()))
                return True
            except Exception as e:
                logger.exception("DB add_ticket_timer failed with timestamp fallback: %s", e)
                return False
        except Exception as e:
            logger.exception("DB add_ticket_timer failed: %s", e)
            return False

    async def _try_db_cancel_ticket_timer(self, channel_id, action):
        if not hasattr(self.bot, "db") or not hasattr(self.bot.db, "cancel_ticket_timer"):
            return False
        try:
            self.bot.db.cancel_ticket_timer(channel_id, action)
            return True
        except Exception as e:
            logger.exception("DB cancel_ticket_timer failed: %s", e)
            return False

    async def _try_db_close_ticket(self, channel_id, closed_at_dt: datetime):
        """
        Try to call bot.db.close_ticket(channel_id, closed_at) with DATETIME string,
        fallback to unix timestamp int. Return True if succeeded.
        """
        if not hasattr(self.bot, "db") or not hasattr(self.bot.db, "close_ticket"):
            return False

        dt_str = self._format_dt_for_db(closed_at_dt)
        try:
            self.bot.db.close_ticket(channel_id, dt_str)
            return True
        except TypeError:
            # fallback to timestamp
            try:
                self.bot.db.close_ticket(channel_id, int(closed_at_dt.timestamp()))
                return True
            except Exception as e:
                logger.exception("DB close_ticket failed with timestamp fallback: %s", e)
                return False
        except Exception as e:
            logger.exception("DB close_ticket failed: %s", e)
            return False

    # ---------------- Transcript ----------------

    async def generate_transcript(self, channel: discord.TextChannel) -> discord.File:
        transcript = ""
        os.makedirs(IMAGE_DIR, exist_ok=True)
        async for msg in channel.history(limit=None, oldest_first=True):
            transcript += f"[{msg.created_at}] {msg.author}: {msg.content}\n"
            for attachment in msg.attachments:
                # Save all images, regardless of sender
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    image_path = os.path.join(IMAGE_DIR, f"{channel.id}_{attachment.id}_{attachment.filename}")
                    async with aiohttp.ClientSession() as session:
                        async with session.get(attachment.url) as resp:
                            if resp.status == 200:
                                with open(image_path, "wb") as f:
                                    f.write(await resp.read())
                    transcript += f"[Image saved: {image_path}]\n"
                else:
                    transcript += f"[Attachment: {attachment.url}]\n"
            transcript += "\n"

        transcript_path = os.path.join(TRANSCRIPT_DIR, f"{channel.id}.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript)

        return discord.File(transcript_path, filename="transcript.txt")

    # ---------------- Role Checks ----------------

    def jrmod_or_manage_channels():
        async def predicate(ctx: commands.Context):
            allowed = {JUNIOR_MOD_ROLE_ID, ADDITIONAL_STAFF_ROLE_ID}
            if any(r.id in allowed for r in ctx.author.roles):
                return True
            return ctx.author.guild_permissions.manage_channels
        return commands.check(predicate)

    # ---------------- Logging Helper ----------------

    async def _log_ticket(self, channel: discord.TextChannel, author: discord.Member = None):
        """Generates and sends a transcript to the log channel."""
        log_channel = self.bot.get_channel(self.log_channel_id)
        if not log_channel:
            return False

        transcript = await self.generate_transcript(channel)
        embed = discord.Embed(
            title="Transcript generated",
            description=f"Ticket logged: `{channel.name}`" + (f" by {author.mention}" if author else ""),
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        await log_channel.send(embed=embed, file=transcript)
        return True

    # ---------------- Commands ----------------

    @commands.command(name="cancelclose")
    @commands.has_permissions(manage_channels=True)
    async def cancel_close(self, ctx: commands.Context):
        """Cancel a scheduled close (DB and internal fallback)."""
        cancelled_db = await self._try_db_cancel_ticket_timer(ctx.channel.id, "close")

        task = self.delayed_closures.pop(ctx.channel.id, None)
        if task:
            task.cancel()

        if cancelled_db or task:
            embed = discord.Embed(
                description="❌ Scheduled close canceled.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
        else:
            embed = discord.Embed(
                description="No scheduled close found for this channel.",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
        await ctx.send(embed=embed)


    @commands.command(name="close")
    @commands.has_permissions(manage_channels=True)
    async def close_ticket(self, ctx: commands.Context, time: str = None):
        """
        Schedule a close for this ticket. Accepts:
        - 1:30 (hours:minutes)
        - 1:30:00 (h:m:s)
        - 90m, 1h30m, 3600s
        - 15 (minutes)
        """
        if not ctx.channel.category or ctx.channel.category.id not in self.ticket_category_ids:
            await ctx.send(embed=discord.Embed(
                description="This command can only be used in ticket channels.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            ))
            return

        # if no time is given, treat as instant close
        delay_seconds = 0
        if time:
            try:
                delay_seconds = self._parse_time_to_seconds(time)
                if delay_seconds < 0:
                    raise ValueError("Negative delay not allowed")
            except Exception:
                await ctx.send(embed=discord.Embed(
                    description="Invalid time format. Try `1:30`, `90m`, `1h30m`, or `15` (minutes).",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                ))
                return

        user_id = self._get_user_id_from_topic(ctx.channel.topic or "")
        if not user_id:
            for uid, ch_id in self.open_tickets.items():
                if ch_id == ctx.channel.id:
                    user_id = uid
                    break

        if not user_id:
            await ctx.send(embed=discord.Embed(
                description="Could not determine ticket owner (missing user ID).",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            ))
            return

        if delay_seconds == 0:
            # instant close
            await ctx.send(embed=discord.Embed(
                description="⏹️ Closing ticket immediately...",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            ))
            await self._delayed_close_channel(ctx.channel, 0, scheduled_by=ctx.author)
            return

        # schedule delayed close as before
        execute_at_dt = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        db_saved = await self._try_db_add_ticket_timer(ctx.channel.id, user_id, "close", execute_at_dt)

        if db_saved:
            desc = f"⏲️ Ticket will close at {self._format_dt_for_db(execute_at_dt)} UTC unless canceled with `!cancelclose`."
            await ctx.send(embed=discord.Embed(description=desc, color=discord.Color.orange(), timestamp=datetime.now(timezone.utc)))
            return

        existing = self.delayed_closures.get(ctx.channel.id)
        if existing:
            existing.cancel()

        task = asyncio.create_task(self._delayed_close_channel(ctx.channel, delay_seconds, scheduled_by=ctx.author))
        self.delayed_closures[ctx.channel.id] = task

        hours = delay_seconds // 3600
        minutes = (delay_seconds % 3600) // 60
        desc = f"⏲️ Ticket will close in {hours}h {minutes}m unless canceled with `!cancelclose`."
        await ctx.send(embed=discord.Embed(description=desc, color=discord.Color.orange(), timestamp=datetime.now(timezone.utc)))
        await ctx.send(embed=discord.Embed(description=desc, color=discord.Color.orange(), timestamp=datetime.now(timezone.utc)))

    async def _delayed_close_channel(self, channel: discord.TextChannel, delay: int, scheduled_by: discord.Member = None):
        """Internal (non-persistent) close task."""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        # Try to send a notifying message
        try:
            await channel.send(embed=discord.Embed(
                description="Closing ticket due to inactivity.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            ))
        except Exception:
            pass

        # Try to mark closed in DB (with closed_at)
        closed_at_dt = datetime.now(timezone.utc)
        db_closed = await self._try_db_close_ticket(channel.id, closed_at_dt)
        if not db_closed:
            logger.debug("DB close_ticket not available or failed for channel %s", channel.id)

        # generate and send transcript to log channel
        try:
            await self._log_ticket(channel)
        except Exception:
            logger.exception("Failed generating or sending transcript during auto-close for channel %s", getattr(channel, "id", None))

        # ---------------- Automatic notifications ----------------
        user = None
        try:
            user_id = self._get_user_id_from_topic(getattr(channel, "topic", "") or "")
            if user_id:
                user = await self.bot.fetch_user(user_id)
        except Exception:
            pass

        if user:
            # Send DM to user notifying ticket closure
            try:
                dm_embed = discord.Embed(
                    title="Your Ticket Has Been Closed",
                    description=(
                        "Hello! Your ticket has been closed by our staff.\n\n"
                        "If you need further assistance, feel free to open a new ticket."
                    ),
                    color=discord.Color.blue(),
                    timestamp=datetime.now(timezone.utc)
                )
                await user.send(embed=dm_embed)
            except discord.Forbidden:
                # Can't DM user
                try:
                    await channel.send(embed=discord.Embed(
                        description=f"❌ Could not DM {user.name}. They may have DMs disabled.",
                        color=discord.Color.red(),
                        timestamp=datetime.now(timezone.utc)
                    ))
                except Exception:
                    pass
        else:
            # User has left the server
            try:
                await channel.send(embed=discord.Embed(
                    title="Ticket Closed",
                    description="The user has left the server. Ticket closed automatically.",
                    color=discord.Color.orange(),
                    timestamp=datetime.now(timezone.utc)
                ))
            except Exception:
                pass

        # attempt to delete the channel
        try:
            await channel.delete()
        except Exception:
            logger.exception("Failed to delete channel %s during auto-close", getattr(channel, "id", None))

        # cleanup internal state
        self.delayed_closures.pop(channel.id, None)
        # clean open_tickets mapping if present
        for uid, ch in list(self.open_tickets.items()):
            if ch == channel.id:
                del self.open_tickets[uid]
                
    @commands.command(name="log")
    @jrmod_or_manage_channels()
    async def log_ticket(self, ctx: commands.Context):
        if not ctx.channel.category or ctx.channel.category.id not in self.ticket_category_ids:
            await ctx.send(embed=discord.Embed(
                description="This command can only be used in ticket channels.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            ))
            return

        success = await self._log_ticket(ctx.channel, author=ctx.author)
        if success:
            await ctx.send(embed=discord.Embed(
                description="Ticket has been logged with transcript.",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            ))
        else:
            await ctx.send(embed=discord.Embed(
                description="Failed to log ticket.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            ))

    @commands.command(name="suspend")
    @commands.has_permissions(manage_channels=True)
    async def suspend_ticket(self, ctx: commands.Context):
        """
        Suspend: schedule an auto-close in 24 hours if the user doesn't respond.
        This stores a suspend timer to DB if possible; otherwise it does nothing persistent.
        """
        delay_seconds = 86400  # 24h
        user_id = self._get_user_id_from_topic(ctx.channel.topic or "")
        if not user_id:
            await ctx.send(embed=discord.Embed(
                description="Could not determine ticket owner (missing user ID in topic).",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            ))
            return

        execute_at_dt = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        db_saved = await self._try_db_add_ticket_timer(ctx.channel.id, user_id, "suspend", execute_at_dt)
        if not db_saved:
            logger.debug("DB suspend timer not saved; no persistent suspend scheduled for channel %s", ctx.channel.id)

        await ctx.send(embed=discord.Embed(
            description="🚫 Ticket suspended. Will close in 24 hours if user does not reply.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        ))

        # automatically log suspended ticket
        try:
            await self._log_ticket(ctx.channel, author=ctx.author)
        except Exception:
            logger.exception("Failed to log ticket during suspend for channel %s", ctx.channel.id)

    # ---------------- NotifyMe Role Check ----------------

    def jrmod_or_manage_channels():
        async def predicate(ctx: commands.Context):
            allowed = {JUNIOR_MOD_ROLE_ID, ADDITIONAL_STAFF_ROLE_ID}
            if any(r.id in allowed for r in ctx.author.roles):
                return True
            if ctx.author.guild_permissions.manage_channels:
                return True
            return False
        return commands.check(predicate)

    @commands.command(name="notifyme")
    @jrmod_or_manage_channels()
    async def notify_me(self, ctx: commands.Context):
        try:
            if hasattr(self.bot, "db") and hasattr(self.bot.db, "add_watcher"):
                # Prevent duplicate watcher entries
                current_watchers = []
                if hasattr(self.bot.db, "get_watchers"):
                    current_watchers = self.bot.db.get_watchers(ctx.channel.id)
                if ctx.author.id in current_watchers:
                    await ctx.send(embed=discord.Embed(
                        description="You already have subscribed to this channel.",
                        color=discord.Color.orange(),
                        timestamp=datetime.now(timezone.utc)
                    ))
                    return
                self.bot.db.add_watcher(ctx.channel.id, ctx.author.id)
        except Exception:
            logger.exception("Failed to add watcher via DB; falling back to in-memory if desired.")

        await ctx.send(embed=discord.Embed(
            description="✅ You'll be notified when the user responds.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        ))
        
    @commands.Cog.listener()
    async def on_typing(self, channel, user, when):
        # Only respond to user typing in DM (private channel)
        if isinstance(channel, discord.DMChannel) and not user.bot:
            # Find the open ticket channel for this user
            ticket_channel_id = self.bot.db.get_open_ticket_channel_id(user.id)
            if ticket_channel_id:
                guild = self.bot.get_guild(self.guild_id)
                ticket_channel = guild.get_channel(ticket_channel_id)
                if ticket_channel:
                    await ticket_channel.send(f"**{user} is typing...**", delete_after=5)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """
        Triggered when a guild channel is deleted.

        Only log a warning if the deleted channel is a ticket channel.
        Do NOT try to fetch its history, because it's already deleted.
        """
        if channel.category_id in self.ticket_category_ids:
            logger.warning(
                f"Ticket channel {channel.id} in category {channel.category_id} was deleted. "
                "Transcript generation skipped because channel no longer exists."
            )


    @commands.Cog.listener()
    async def on_message(self, message):
        # Only react to DMs from users (not bots)
        if isinstance(message.channel, discord.DMChannel) and not message.author.bot:
            try:
                await message.add_reaction("✅")
            except Exception:
                pass

            # Notify watchers in the ticket channel
            ticket_channel_id = None
            if hasattr(self.bot.db, "get_open_ticket_channel_id"):
                ticket_channel_id = self.bot.db.get_open_ticket_channel_id(message.author.id)
            if ticket_channel_id:
                guild = self.bot.get_guild(self.guild_id)
                ticket_channel = guild.get_channel(ticket_channel_id)
                if ticket_channel and hasattr(self.bot.db, "get_watchers"):
                    watchers = self.bot.db.get_watchers(ticket_channel_id)
                    mentions = [guild.get_member(w).mention for w in set(watchers) if guild.get_member(w)]


# Required for loading as an extension
async def setup(bot):
    await bot.add_cog(Modmail(bot))

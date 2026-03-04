import discord
from discord.ext import commands
import re
import io
import os
import json
import asyncio
from datetime import datetime, timezone
from config import (
    JUNIOR_MOD_ROLE_ID, ADDITIONAL_STAFF_ROLE_ID, STAFF_ROLES,
    ALLOWED_CATEGORIES, DISALLOWED_CATEGORY, TRANSCRIPT_DIR
)
from bot import ClaimTicketButton  # your custom button class
from note_manager import NoteManager


class NotesView(discord.ui.View):
    """Paginated view for displaying user notes with arrow navigation."""
    def __init__(self, notes: list, user_id: int, user_name: str):
        super().__init__(timeout=180)
        self.notes = notes
        self.user_id = user_id
        self.user_name = user_name
        self.current_page = 0

    def _build_embed(self) -> discord.Embed:
        """Build the embed for the current page."""
        if not self.notes:
            return discord.Embed(
                title=f"📝 Notes for {self.user_name}",
                description="No notes on record.",
                color=discord.Color.orange()
            )
        
        note = self.notes[self.current_page]
        embed = discord.Embed(
            title=f"📝 Notes for {self.user_name}",
            description=note["note"],
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="By", value=note["staff"], inline=True)
        embed.add_field(name="Date", value=note["created_at"], inline=True)
        embed.set_footer(text=f"Note {self.current_page + 1}/{len(self.notes)}")
        return embed

    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        else:
            self.current_page = len(self.notes) - 1
        await interaction.response.edit_message(embed=self._build_embed())

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.notes) - 1:
            self.current_page += 1
        else:
            self.current_page = 0
        await interaction.response.edit_message(embed=self._build_embed())


class TranscriptView(discord.ui.View):
    """Paginated view for displaying transcript messages with arrow navigation."""
    def __init__(self, messages: list, channel_name: str, saved_at: str):
        super().__init__(timeout=180)
        self.messages = messages
        self.channel_name = channel_name
        self.saved_at = saved_at
        self.current_page = 0

    def _build_embed(self) -> discord.Embed:
        """Build the embed for the current message (or cluster of messages)."""
        if not self.messages:
            return discord.Embed(
                title=f"📋 Transcript - {self.channel_name}",
                description="No messages in transcript.",
                color=discord.Color.orange()
            )
        
        msg = self.messages[self.current_page]
        content = msg["content"][:1024] if msg["content"] else "*No content*"
        
        embed = discord.Embed(
            title=f"📋 Transcript - {self.channel_name}",
            description=content,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Role", value=msg["role"], inline=True)
        embed.add_field(name="Author", value=msg["author"], inline=True)
        embed.add_field(name="Time", value=msg["timestamp"], inline=True)
        embed.set_footer(text=f"Message {self.current_page + 1}/{len(self.messages)} | Saved {self.saved_at}")
        return embed

    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        else:
            self.current_page = len(self.messages) - 1
        await interaction.response.edit_message(embed=self._build_embed())

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.messages) - 1:
            self.current_page += 1
        else:
            self.current_page = 0
        await interaction.response.edit_message(embed=self._build_embed())


def get_staff_position(member: discord.Member):
    """Return highest staff role of a member."""
    for role_id in STAFF_ROLES:
        if any(r.id == role_id for r in member.roles):
            return STAFF_ROLES[role_id]
    return "Staff"

def staff_or_manage_channels():
    async def predicate(ctx: commands.Context):
        allowed = {JUNIOR_MOD_ROLE_ID, ADDITIONAL_STAFF_ROLE_ID}
        if any(r.id in allowed for r in ctx.author.roles):
            return True
        return ctx.author.guild_permissions.manage_channels
    return commands.check(predicate)

class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.note_manager = NoteManager(bot)

    # ------------------ Helpers ------------------

    def build_embed(self, title, description, color, author=None, footer_text=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        if author:
            embed.set_author(name=str(author), icon_url=author.display_avatar.url)
        if footer_text:
            embed.set_footer(text=footer_text)
        return embed

    async def get_user_from_channel(self, channel: discord.TextChannel):
        """Extract user from channel.topic using regex (expects '(123456789012345678)')"""
        if channel.topic:
            match = re.search(r"\((\d{17,20})\)", channel.topic)
            if match:
                user_id = int(match.group(1))
                return self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        return None

    async def check_junior_mod(self, ctx):
        if ctx.author.bot:
            return False
        role_ids = [role.id for role in ctx.author.roles]
        return JUNIOR_MOD_ROLE_ID in role_ids

    # ------------------ DX Premade Responses ------------------

    @commands.command(name="dxadd")
    @commands.has_permissions(manage_guild=True)
    async def add_dx_response(self, ctx, key: str, *, response: str):
        if await self.check_junior_mod(ctx):
            await ctx.send("🚫 You are not allowed to use this command.")
            return
        existing = self.bot.db.get_dx_response(key)
        if existing:
            await ctx.send(embed=self.build_embed(
                "Add Failed",
                f"Response with key `{key}` already exists.",
                discord.Color.red()
            ))
            return
        self.bot.db.add_dx_response(key, response)
        await ctx.send(embed=self.build_embed(
            "Premade Response Added",
            f"Key `{key}` added with response:\n{response}",
            discord.Color.green()
        ))

    @commands.command(name="dx")
    async def list_dx_responses(self, ctx):
        responses = self.bot.db.get_all_dx_responses()
        if not responses:
            await ctx.send(embed=self.build_embed(
                "No Premade Responses",
                "No premade responses found in the database.",
                discord.Color.red()
            ))
            return
        keys = "\n".join(f"`{r['key']}`" for r in responses)
        await ctx.send(embed=self.build_embed(
            "Available Premade Response Keys",
            keys,
            discord.Color.purple()
        ))

    @commands.command(name="msg")
    async def preview_dx_response(self, ctx, key: str):
        """Preview a premade DX response inside the current ticket channel (junior mods allowed)."""
        response = self.bot.db.get_dx_response(key)
        if not response:
            await ctx.send(embed=self.build_embed(
                "Preview Failed",
                f"No premade response found for key `{key}`.",
                discord.Color.red(),
                ctx.author
            ))
            return

        is_ticket_channel = isinstance(ctx.channel, discord.TextChannel) and ctx.channel.name.startswith("dx-")
        if not is_ticket_channel:
            await ctx.send(embed=self.build_embed(
                "Invalid Channel",
                "⚠️ This command can only be used inside ticket channels.",
                discord.Color.red(),
                ctx.author
            ))
            return

        preview_embed = self.build_embed(
            f"Preview of `{key}`",
            response,
            discord.Color.orange(),
            self.bot.user,
            footer_text="(This is only a preview, not sent to the user.)"
        )
        await ctx.send(embed=preview_embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.content.startswith("!") or message.author.bot:
            return
        ctx = await self.bot.get_context(message)
        cmd_key = message.content[1:].split()[0]
        response = self.bot.db.get_dx_response(cmd_key)
        if not response:
            return
        is_ticket_channel = isinstance(ctx.channel, discord.TextChannel) and ctx.channel.name.startswith("dx-")
        try:
            if is_ticket_channel:
                user = await self.get_user_from_channel(ctx.channel)
                if not user:
                    await ctx.send("Unable to find the user from this ticket channel.")
                    return
                embed_user = self.build_embed("", response, discord.Color.orange(), self.bot.user)
                user_msg = await user.send(embed=embed_user)
                embed_staff = self.build_embed(
                    f"Premade Reply `{cmd_key}` Sent",
                    response,
                    discord.Color.green(),
                    ctx.author,
                    footer_text=f"CCACMsgCode:{user_msg.id}"
                )
                await ctx.channel.send(embed=embed_staff)
            else:
                embed = self.build_embed(f"Premade Reply `{cmd_key}`", response, discord.Color.green(), ctx.author)
                await ctx.channel.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=self.build_embed("Failed to Send", str(e), discord.Color.red()))
   

    # ------------------ DM / Reply Commands ------------------

    @commands.command(name="r")
    @staff_or_manage_channels()
    async def reply_to_user(self, ctx, *, message: str = ""):
        user = await self.get_user_from_channel(ctx.channel)
        if not user:
            await ctx.send("Unable to find the user from this ticket channel.")
            return
        try:
            image_url = None
            if ctx.message.attachments:
                for attachment in ctx.message.attachments:
                    if attachment.content_type and attachment.content_type.startswith("image/"):
                        image_url = attachment.url
                        break
            user_embed = self.build_embed("", message, discord.Color.orange(), self.bot.user)
            if image_url:
                user_embed.set_image(url=image_url)
            user_msg = await user.send(embed=user_embed)
            staff_position = get_staff_position(ctx.author)
            staff_embed = self.build_embed(
                "",
                "STAFF RESPONSE:\n" + message,
                discord.Color.green(),
                ctx.author,
                footer_text=f"{staff_position} | CCACMsgCode:{user_msg.id}"
            )
            if image_url:
                staff_embed.set_image(url=image_url)
            await ctx.channel.send(embed=staff_embed)
            await ctx.message.delete()
        except Exception as e:
            await ctx.send(embed=self.build_embed("Error", f"Failed to send reply: {e}", discord.Color.red()))

    @commands.command(name="re")
    async def edit_reply(self, ctx, *, new_message: str = ""):
        try:
            if not ctx.message.reference or not isinstance(ctx.message.reference.resolved, discord.Message):
                await ctx.send(embed=self.build_embed("Error", "You must reply to the old bot message containing the CCACMsgCode.", discord.Color.red()))
                return
            replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            msg_id = replied_msg.embeds[0].footer.text.replace("CCACMsgCode:", "").split("|")[-1].strip()
            user = await self.get_user_from_channel(ctx.channel)
            dm_channel = await user.create_dm()
            target_msg = await dm_channel.fetch_message(int(msg_id))
            old_embed = target_msg.embeds[0]

            image_url = old_embed.image.url if old_embed.image else None
            if ctx.message.attachments:
                for attachment in ctx.message.attachments:
                    if attachment.content_type and attachment.content_type.startswith("image/"):
                        image_url = attachment.url
                        break

            description = new_message if new_message.strip() else old_embed.description
            new_embed = discord.Embed(title=old_embed.title, description=description, color=discord.Color.orange(), timestamp=old_embed.timestamp)
            if old_embed.author:
                new_embed.set_author(name=old_embed.author.name, icon_url=old_embed.author.icon_url)
            if old_embed.footer:
                new_embed.set_footer(text=old_embed.footer.text, icon_url=old_embed.footer.icon_url)
            if image_url:
                new_embed.set_image(url=image_url)
            await target_msg.edit(embed=new_embed)

            staff_position = get_staff_position(ctx.author)
            staff_embed = discord.Embed(
                title=replied_msg.embeds[0].title,
                description=description,
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            if replied_msg.embeds[0].author:
                staff_embed.set_author(name=replied_msg.embeds[0].author.name, icon_url=replied_msg.embeds[0].author.icon_url)
            staff_embed.set_footer(text=f"{staff_position} | CCACMsgCode:{msg_id}")
            if image_url:
                staff_embed.set_image(url=image_url)
            await replied_msg.edit(embed=staff_embed)
            await ctx.message.delete()
        except Exception as e:
            await ctx.send(embed=self.build_embed("Edit Failed", str(e), discord.Color.red()))

    @commands.command(name="delete")
    @staff_or_manage_channels()
    async def delete_message(self, ctx):
        try:
            if not ctx.message.reference or not isinstance(ctx.message.reference.resolved, discord.Message):
                await ctx.send(embed=self.build_embed("Error", "You must reply to the staff confirmation message containing CCACMsgCode.", discord.Color.red()))
                return
            replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            msg_id = replied_msg.embeds[0].footer.text.replace("CCACMsgCode:", "").strip()
            user = await self.get_user_from_channel(ctx.channel)
            dm_channel = await user.create_dm()
            target_msg = await dm_channel.fetch_message(int(msg_id))
            await target_msg.delete()
            await replied_msg.delete()
            await ctx.message.delete()
            await ctx.send(embed=self.build_embed("Success", f"Deleted message sent to {user.mention}.", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=self.build_embed("Delete Failed", str(e), discord.Color.red()))

    # ------------------ Ticket Transfer / Contact ------------------

    @commands.command(name="transfer")
    @staff_or_manage_channels()
    async def transfer_ticket(self, ctx, new_mod: discord.Member):
        if ctx.channel.category_id is None:
            await ctx.send("❌ This command can only be used inside a ticket channel.")
            return
        self.bot.db.assign_mod_to_ticket(ctx.channel.id, new_mod.id, new_mod.name)
        await ctx.send(f"✅ Ticket has been transferred to {new_mod.mention}.\nThey are now responsible for this ticket.")

    @commands.command(name="contact")
    @staff_or_manage_channels()
    async def contact_user(self, ctx, user_id: int, *, reason: str = "No reason provided"):
        try:
            user = await self.bot.fetch_user(user_id)
            if not user:
                await ctx.send(embed=self.build_embed("Contact Failed", f"User with ID `{user_id}` could not be found.", discord.Color.red(), ctx.author))
                return
            guild = self.bot.get_guild(1346839676333461625)
            category = guild.get_channel(1346881466881146910)
            channel_name = f"dx-{user.name}".replace(" ", "-").lower()
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Contact ticket with {user} ({user.id})"
            )
            self.bot.db.create_ticket_entry(user=user, channel=ticket_channel, category_id=category.id, ticket_type="contact")
            staff_embed = self.build_embed("Contact Ticket Opened", f"A new contact ticket has been opened with {user.mention}.\nReason: {reason}", discord.Color.green(), ctx.author)
            await ticket_channel.send(embed=staff_embed, view=ClaimTicketButton(ticket_channel.id))
            try:
                user_embed = self.build_embed("Staff Contact", f"Our staff has opened a ticket with you:\n\n{reason}", discord.Color.orange(), self.bot.user)
                await user.send(embed=user_embed)
            except discord.Forbidden:
                await ticket_channel.send(embed=self.build_embed("DM Failed", "❌ Could not DM the user (they may have DMs disabled).", discord.Color.red()))
            await ctx.send(embed=self.build_embed("Success", f"Ticket opened with {user.mention} in {ticket_channel.mention}.", discord.Color.green(), ctx.author))
        except Exception as e:
            await ctx.send(embed=self.build_embed("Error", str(e), discord.Color.red(), ctx.author))

    # ------------------ Utility helpers ------------------

    def _parse_time_to_seconds(self, timestr: str) -> int:
        """Convert simple expressions to seconds (hrs/days/hh:mm)."""
        if not timestr:
            raise ValueError("Empty time string")
        s = timestr.strip().lower()
        if s.endswith("d"):
            return int(float(s[:-1]) * 86400)
        if s.endswith("h"):
            return int(float(s[:-1]) * 3600)
        if ":" in s:
            parts = s.split(":")
            if len(parts) == 2:
                h, m = map(int, parts)
                return h * 3600 + m * 60
            elif len(parts) == 3:
                h, m, sec = map(int, parts)
                return h * 3600 + m * 60 + sec
        # plain number treated as minutes
        return int(float(s) * 60)

    # ------------------ Notes / tracking commands ------------------

    @commands.command(name="note")
    @staff_or_manage_channels()
    async def note_user(self, ctx, *, message: str):
        """Leave a note for the user; notes persist across tickets."""
        user = await self.get_user_from_channel(ctx.channel)
        if not user:
            await ctx.send("Unable to determine user associated with this channel.")
            return
        self.note_manager.add_note(user.id, message, str(ctx.author))
        await ctx.send(embed=self.build_embed("Note Added", f"Saved note for {user.mention}.", discord.Color.green()))

    @commands.command(name="trs")
    @staff_or_manage_channels()
    async def trs(self, ctx, user_id: int):
        """Show transcripts and notes for a user (both with pagination embeds)."""
        try:
            user = await self.bot.fetch_user(user_id)
            user_name = str(user)
        except Exception:
            user_name = f"User {user_id}"
        
        notes = self.note_manager.get_notes(user_id)
        transcripts = TranscriptManager.load_transcripts(user_id)
        
        # If no notes or transcripts, inform user
        if not notes and not transcripts:
            await ctx.send(embed=discord.Embed(
                title=f"📋 User Record for {user_name}",
                description="No notes or transcripts on record.",
                color=discord.Color.orange()
            ))
            return
        
        # Start with showing notes if available
        if notes:
            notes_data = [{
                "note": n["note"],
                "staff": n["staff"],
                "created_at": str(n["created_at"]) if n["created_at"] else "Unknown"
            } for n in notes]
            
            view = NotesView(notes_data, user_id, user_name)
            await ctx.send(embed=view._build_embed(), view=view)
        
        # Then show transcripts if available
        if transcripts:
            for entry in transcripts:
                if entry["messages"]:
                    view = TranscriptView(entry["messages"], entry["channel"], entry["saved_at"])
                    await ctx.send(embed=view._build_embed(), view=view)

    @commands.command(name="remindme")
    @staff_or_manage_channels()
    async def remind_me(self, ctx, about: str, when: str):
        """Remind yourself about something after a delay."""
        try:
            seconds = self._parse_time_to_seconds(when)
        except Exception:
            await ctx.send("Invalid time format. Try `1h`, `2d`, `1:30`, etc.")
            return
        await ctx.send(f"⏲️ Reminder set for {when} from now.")
        async def _reminder():
            await asyncio.sleep(seconds)
            try:
                await ctx.author.send(f"⏰ Reminder: {about}")
            except Exception:
                pass
        self.bot.loop.create_task(_reminder())

    @commands.command(name="anon")
    @staff_or_manage_channels()
    async def anonymous_reply(self, ctx, *, message: str = ""):
        """Reply to the user without disclosing your name."""
        user = await self.get_user_from_channel(ctx.channel)
        if not user:
            await ctx.send("Unable to find the ticket user.")
            return
        try:
            user_embed = self.build_embed("", message, discord.Color.orange(), self.bot.user)
            user_msg = await user.send(embed=user_embed)
            staff_embed = self.build_embed("", "STAFF RESPONSE (anonymous):\n" + message, discord.Color.green(), author=None)
            await ctx.channel.send(embed=staff_embed)
            await ctx.message.delete()
        except Exception as e:
            await ctx.send(embed=self.build_embed("Error", f"Failed to send anonymous reply: {e}", discord.Color.red()))

    @commands.command(name="raw")
    @staff_or_manage_channels()
    async def raw(self, ctx):
        """Show the raw user ID for the current ticket channel."""
        user = await self.get_user_from_channel(ctx.channel)
        if user:
            await ctx.send(str(user.id))
        else:
            await ctx.send("Could not determine user ID.")

    @commands.command(name="language")
    @staff_or_manage_channels()
    async def language(self, ctx, lng: str, *, text: str = None):
        """Translate messages to/from a given language (placeholder)."""
        await ctx.send("🌐 Language translation feature coming in a future update.")

    @commands.command(name="stats")
    @staff_or_manage_channels()
    async def stats(self, ctx):
        """Display basic ticket statistics (restricted role)."""
        from cogs.config import STATS_ROLE_ID
        if STATS_ROLE_ID not in [r.id for r in ctx.author.roles]:
            await ctx.send("🚫 You are not authorized to run that command.")
            return
        # compute some simple metrics from transcript files
        now = datetime.now(timezone.utc)
        tickets_today = 0
        response_times = []
        resolution_times = []
        staff_counts = {}
        for fname in os.listdir(TRANSCRIPT_DIR):
            if not fname.endswith('.json') or '_notes' in fname:
                continue
            path = os.path.join(TRANSCRIPT_DIR, fname)
            try:
                with open(path,'r',encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue
            for entry in data:
                saved_at = datetime.strptime(entry['saved_at'], "%Y-%m-%d %H:%M:%S")
                if saved_at.date() == now.date():
                    tickets_today += 1
                msgs = entry.get('messages', [])
                first_user = None
                first_staff = None
                last_time = None
                for m in msgs:
                    t = datetime.strptime(m['timestamp'], "%Y-%m-%d %H:%M:%S")
                    last_time = t if last_time is None or t>last_time else last_time
                    if m['role'].startswith('USER') and first_user is None:
                        first_user = t
                    if m['role'].startswith('STAFF') and first_staff is None:
                        first_staff = t
                        staff_counts[m['author']] = staff_counts.get(m['author'],0)+1
                if first_user and first_staff:
                    response_times.append((first_staff-first_user).total_seconds())
                if first_user and last_time:
                    resolution_times.append((last_time-first_user).total_seconds())
        avg_resp = sum(response_times)/len(response_times) if response_times else 0
        avg_res = sum(resolution_times)/len(resolution_times) if resolution_times else 0
        most_active = max(staff_counts.items(), key=lambda x: x[1])[0] if staff_counts else 'N/A'
        embed = discord.Embed(title="Ticket Stats", color=discord.Color.blue())
        embed.add_field(name="Tickets Today", value=str(tickets_today), inline=False)
        embed.add_field(name="Avg. Response (s)", value=f"{avg_resp:.1f}", inline=False)
        embed.add_field(name="Avg. Resolution (s)", value=f"{avg_res:.1f}", inline=False)
        embed.add_field(name="Most Active Staff", value=most_active, inline=False)
        await ctx.send(embed=embed)

    # ------------------ Transcript Command ------------------
    @commands.command(name="transcript")
    async def transcript_command(self, ctx, user_id: int = None):
        if user_id:
            data = TranscriptManager.load_transcripts(user_id)
            if not data:
                await ctx.send(f"No transcripts found for user ID `{user_id}`.")
                return

            for entry in data:
                if entry["messages"]:
                    view = TranscriptView(entry["messages"], entry["channel"], entry["saved_at"])
                    await ctx.send(embed=view._build_embed(), view=view)
        else:
            if not isinstance(ctx.channel, discord.TextChannel):
                await ctx.send("This command must be run in a text channel.")
                return
            if ctx.channel.category_id == DISALLOWED_CATEGORY:
                await ctx.send("Transcript saving is disabled for this category.")
                return
            if ctx.channel.category_id not in ALLOWED_CATEGORIES:
                await ctx.send("This category is not configured for automatic transcript saving.")
                return

            user = await self.get_user_from_channel(ctx.channel)
            if not user:
                await ctx.send("User could not be resolved from the channel topic.")
                return

            messages = [msg async for msg in ctx.channel.history(limit=None, oldest_first=True)]
            TranscriptManager.save_transcript(user.id, ctx.channel, messages)

            await ctx.send(embed=discord.Embed(
                title="Transcript Saved",
                description=f"Transcript has been saved for user `{user.name}`.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            ))


class TranscriptManager:
    @staticmethod
    def save_transcript(user_id: int, channel: discord.TextChannel, messages):
        transcript_lines = []
        for msg in messages:
            # Check role (user vs staff)
            is_user = msg.author.id == user_id
            is_staff = msg.author.guild_permissions.manage_messages or msg.author.guild_permissions.administrator
            if not (is_user or is_staff):
                continue

            role_label = "USER MESSAGE" if is_user else "STAFF RESPONSE"
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{msg.author.name}#{msg.author.discriminator}"
            content = msg.clean_content or ""

            # Embeds
            for embed in msg.embeds:
                if embed.title:
                    content += f"\n[Embed Title] {embed.title}"
                if embed.description:
                    content += f"\n{embed.description}"
                for field in embed.fields:
                    content += f"\n{field.name}: {field.value}"

            # Attachments
            for attachment in msg.attachments:
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    content += f"\n[Image] {attachment.url}"
                else:
                    content += f"\n[File] {attachment.url}"

            if not content.strip():
                content = "[no text]"

            transcript_lines.append({
                "timestamp": timestamp,
                "author": author,
                "role": role_label,
                "content": content,
            })

        # Save JSON
        os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
        save_path = os.path.join(TRANSCRIPT_DIR, f"{user_id}.json")

        if os.path.exists(save_path):
            with open(save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = []

        data.append({
            "channel": channel.name,
            "category_id": channel.category_id,
            "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "messages": transcript_lines,
        })

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    @staticmethod
    def load_transcripts(user_id: int):
        path = os.path.join(TRANSCRIPT_DIR, f"{user_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []


async def setup(bot):
    await bot.add_cog(StaffCommands(bot))
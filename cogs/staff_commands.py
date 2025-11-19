import discord
from discord.ext import commands
import re
import io
import os
import json
from datetime import datetime, timezone
from config import (
    JUNIOR_MOD_ROLE_ID, ADDITIONAL_STAFF_ROLE_ID, STAFF_ROLES,
    ALLOWED_CATEGORIES, DISALLOWED_CATEGORY, TRANSCRIPT_DIR
)
from bot import ClaimTicketButton  # your custom button class

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
    @commands.has_permissions(manage_channels=True)
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
    @commands.has_permissions(manage_channels=True)
    async def transfer_ticket(self, ctx, new_mod: discord.Member):
        if ctx.channel.category_id is None:
            await ctx.send("❌ This command can only be used inside a ticket channel.")
            return
        self.bot.db.assign_mod_to_ticket(ctx.channel.id, new_mod.id, new_mod.name)
        await ctx.send(f"✅ Ticket has been transferred to {new_mod.mention}.\nThey are now responsible for this ticket.")

    @commands.command(name="contact")
    @commands.has_permissions(manage_guild=True)
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

    # ------------------ Transcript Command ------------------
    @commands.command(name="transcript")
    async def transcript_command(self, ctx, user_id: int = None):
        target_channel_id = 1352669054346854502
        target_channel = self.bot.get_channel(target_channel_id)

        if user_id:
            data = TranscriptManager.load_transcripts(user_id)
            if not data:
                await ctx.send(f"No transcripts found for user ID `{user_id}`.")
                return

            for i, entry in enumerate(data):
                content = "\n".join(
                    f"[{m['timestamp']}] {m['role']} ({m['author']}): {m['content']}"
                    for m in entry["messages"]
                )
                file = discord.File(io.BytesIO(content.encode()), filename=f"ticket_{i+1}.txt")
                transcript_url = f"http://127.0.0.1:5000/index.html?ticket={user_id}"
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="View Transcript", url=transcript_url, style=discord.ButtonStyle.link))
                embed = discord.Embed(
                    title="Transcript Available",
                    description=f"Transcript from `{entry['channel']}` saved on `{entry['saved_at']}`.\n[View Transcript]({transcript_url})",
                    color=discord.Color.blue(),
                )
                if target_channel:
                    await target_channel.send(embed=embed, file=file, view=view)
                else:
                    await ctx.send(embed=embed, file=file, view=view)
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

            transcript_url = f"http://127.0.0.1:5000/index.html?ticket={user.id}"
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="View Transcript", url=transcript_url, style=discord.ButtonStyle.link))
            await ctx.send(f"Transcript has been saved for user `{user.name}`.", view=view)


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
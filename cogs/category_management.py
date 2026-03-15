
from discord.ext import commands
import discord
import logging
import config as app_config

CATEGORY_IDS = getattr(app_config, "CATEGORY_IDS", {})
AUTHORIZED_USER_ID = getattr(app_config, "AUTHORIZED_USER_ID", 0)
JUNIOR_MOD_ROLE_ID = getattr(app_config, "JUNIOR_MOD_ROLE_ID", 0)
ADDITIONAL_STAFF_ROLE_ID = getattr(app_config, "ADDITIONAL_STAFF_ROLE_ID", 0)
STAFF_ROLES = getattr(app_config, "STAFF_ROLES", {})

logger = logging.getLogger("modmail.category")


def staff_or_manage_channels():
    async def predicate(ctx: commands.Context):
        allowed = {role_id for role_id in STAFF_ROLES.keys() if role_id}
        if JUNIOR_MOD_ROLE_ID:
            allowed.add(JUNIOR_MOD_ROLE_ID)
        if ADDITIONAL_STAFF_ROLE_ID:
            allowed.add(ADDITIONAL_STAFF_ROLE_ID)
        if any(r.id in allowed for r in ctx.author.roles):
            return True
        return ctx.author.guild_permissions.manage_channels
    return commands.check(predicate)

class CategoryManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.category_ids = CATEGORY_IDS.copy()

    def _find_category(self, guild: discord.Guild, category_name: str, category_id: int = 0):
        if category_id:
            by_id = guild.get_channel(category_id)
            if isinstance(by_id, discord.CategoryChannel):
                return by_id
        lowered_name = category_name.casefold()
        for category in guild.categories:
            if category.name.casefold() == lowered_name:
                return category
        return None

    @commands.Cog.listener()
    async def on_ready(self):
        guild = discord.utils.get(self.bot.guilds, id=self.bot.guild_id)
        if guild is None:
            return

        for category_name, category_id in list(self.category_ids.items()):
            category = self._find_category(guild, category_name, category_id)
            if category is None and category_name.casefold() == "tech":
                category = await guild.create_category(name="tech")
                logger.info("Created missing tech category with ID %s", category.id)
            if category:
                self.category_ids[category_name] = category.id

    @commands.command(name='move')
    @staff_or_manage_channels()
    async def move_ticket(self, ctx, category_name: str):
        """Move the current ticket to a specified category."""
        category_key = category_name.casefold()
        if category_key not in self.category_ids:
            await ctx.send(f"Category '{category_name}' does not exist.")
            return

        channel = ctx.channel
        new_category_id = self.category_ids[category_key]
        new_category = ctx.guild.get_channel(new_category_id)
        if not isinstance(new_category, discord.CategoryChannel):
            new_category = self._find_category(ctx.guild, category_key, new_category_id)
            if new_category is None and category_key == "tech":
                new_category = await ctx.guild.create_category(name="tech")
                self.category_ids[category_key] = new_category.id
                logger.info("Created tech category on demand with ID %s", new_category.id)

        if new_category:
            await channel.edit(category=new_category)
            await ctx.send(f"Moved ticket to '{new_category.name}' category.")
        else:
            await ctx.send("Failed to move ticket. Category not found.")

    @commands.command(name='create')
    async def create_category(self, ctx, *, category_name: str):
        """Create a new category in the server.

        Allowed for staff members who have one of the special create roles or
        `manage_channels` permission.  This replaces the old `newcc` command.
        """
        # permission check
        allowed_roles = getattr(__import__('cogs.config', fromlist=['CREATE_CATEGORY_ROLES']), 'CREATE_CATEGORY_ROLES')
        if not (any(r.id in allowed_roles for r in ctx.author.roles) or ctx.author.guild_permissions.manage_channels):
            await ctx.send("🚫 You are not authorized to use this command.")
            return

        guild = ctx.guild
        existing = discord.utils.get(guild.categories, name=category_name)
        if existing:
            await ctx.send(f"A category named '{category_name}' already exists.")
            return

        category = await guild.create_category(name=category_name)
        await ctx.send(f"Category '{category_name}' created with ID: {category.id}")


async def setup(bot):
    await bot.add_cog(CategoryManagement(bot))

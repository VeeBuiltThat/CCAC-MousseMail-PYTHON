from discord.ext import commands
import discord
from config import CATEGORY_IDS, AUTHORIZED_USER_ID

class CategoryManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.category_ids = CATEGORY_IDS.copy()

    @commands.Cog.listener()
    async def on_ready(self):
        guild = discord.utils.get(self.bot.guilds, id=self.bot.guild_id)
        for category_name in self.category_ids.keys():
            category = discord.utils.get(guild.categories, name=category_name)
            if category:
                self.category_ids[category_name] = category.id

    @commands.command(name='move')
    @commands.has_permissions(manage_channels=True)
    async def move_ticket(self, ctx, category_name: str):
        """Move the current ticket to a specified category."""
        if category_name not in self.category_ids:
            await ctx.send(f"Category '{category_name}' does not exist.")
            return

        channel = ctx.channel
        new_category_id = self.category_ids[category_name]
        new_category = self.bot.get_channel(new_category_id)

        if new_category:
            await channel.edit(category=new_category)
            await ctx.send(f"Moved ticket to '{category_name}' category.")
        else:
            await ctx.send("Failed to move ticket. Category not found.")

    @commands.command(name='newcc')
    @commands.has_permissions(manage_channels=True)
    async def create_category(self, ctx, *, category_name: str):
        """Create a new category in the server. Only allowed for a specific user."""
        if ctx.author.id != AUTHORIZED_USER_ID:
            await ctx.send("You are not authorized to use this command.")
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

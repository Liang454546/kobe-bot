import discord
from typing import Any


class HubView(discord.ui.View):
    """Buttons for quick actions used by EconomyCog.

    Expects the parent cog instance to implement async helpers:
      - _join(user)
      - _daily(user)
      - _work(user)
      - _wallet(user)
    """

    def __init__(self, cog: Any):
        super().__init__(timeout=120)
        self.cog = cog

    async def _respond(self, interaction: discord.Interaction, message: str):
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="加入賭場", style=discord.ButtonStyle.success, emoji="🎟️")
    async def join_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._respond(interaction, await self.cog._join(interaction.user))

    @discord.ui.button(label="每日簽到", style=discord.ButtonStyle.primary, emoji="🗓️")
    async def daily_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._respond(interaction, await self.cog._daily(interaction.user))

    @discord.ui.button(label="我要打工", style=discord.ButtonStyle.primary, emoji="🛠️")
    async def work_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._respond(interaction, await self.cog._work(interaction.user))

    @discord.ui.button(label="查餘額", style=discord.ButtonStyle.secondary, emoji="💰")
    async def balance_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._respond(interaction, await self.cog._wallet(interaction.user))

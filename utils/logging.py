import os
from typing import Optional

import discord

LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))


async def send_log(bot: discord.Client, message: str) -> None:
    if not LOG_CHANNEL_ID:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return
    await channel.send(message)


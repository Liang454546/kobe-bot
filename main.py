import logging
import os

import discord
from discord.ext import commands

from db import close_db, init_db
from keep_alive import keep_alive

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class KobeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.remove_command("help")

    async def setup_hook(self):
        await init_db()
        await self.load_extension("cogs.events")
        await self.load_extension("cogs.economy")
        await self.load_extension("cogs.games")
        await self.tree.sync()

    async def close(self):
        await close_db()
        await super().close()


def run():
    keep_alive()
    token = os.getenv("TOKEN")
    if not token:
        raise RuntimeError("找不到環境變數 TOKEN，無法啟動機器人。")
    bot = KobeBot()
    bot.run(token)


if __name__ == "__main__":
    run()


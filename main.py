# main.py
import discord
from discord.ext import commands
import os
from keep_alive import keep_alive, auto_ping  # 匯入我們剛剛的終極版

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 載入你的 cogs
async def load_cogs():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")

@bot.event
async def on_ready():
    await load_cogs()
    print(f"【{bot.user} 已上線】曼巴時刻啟動！")

# ============ 啟動順序超級重要！============
if __name__ == "__main__":
    keep_alive()      # 第 1：先開 Flask 佔住 port
    auto_ping()       # 第 2：可選，超級保險
    bot.run(os.getenv("TOKEN"))  # 第 3：最後才跑 Bot

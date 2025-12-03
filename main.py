# main.py
import discord
from discord.ext import commands
import os
import asyncio
from keep_alive import keep_alive, auto_ping

# 設定權限
intents = discord.Intents.default()
intents.message_content = True 
intents.voice_states = True
intents.members = True

# 🔥 關鍵修改：加上 help_command=None
# 這一步會關閉系統預設的文字版 help，讓您的 cogs/help.py (圖形介面) 接管 !h 指令
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# 載入所有 cogs
async def load_cogs():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            try:
                await bot.load_extension(f"cogs.{filename[:-3]}")
                print(f"✅ 載入模組: {filename}")
            except Exception as e:
                print(f"❌ 無法載入 {filename}: {e}")

@bot.event
async def on_ready():
    await load_cogs()
    print(f"【{bot.user} 已上線】曼巴時刻啟動！")

if __name__ == "__main__":
    keep_alive()      
    auto_ping()       
    bot.run(os.getenv("TOKEN"))

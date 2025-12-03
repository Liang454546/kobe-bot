# main.py
import discord
from discord.ext import commands
import os
import asyncio
from keep_alive import keep_alive, auto_ping

# 設定權限
intents = discord.Intents.default()
intents.message_content = True # 務必開啟，否則讀不到訊息
intents.voice_states = True
intents.members = True

# 🔥 關鍵修改：加上 help_command=None
# 這會關閉預設的醜介面，讓您的 cogs/help.py 可以順利載入
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
    print(f"【{bot.user} 已上線】曼巴時刻啟動！")
    # 建議在這裡呼叫，確保 Bot 準備好後才載入 (雖然在 main 呼叫也可以)
    # await load_cogs() 

# 啟動流程
async def main():
    async with bot:
        await load_cogs() # 載入模組
        await bot.start(os.getenv("TOKEN"))

if __name__ == "__main__":
    keep_alive()      # 1. 啟動 Web Server
    auto_ping()       # 2. 啟動自動 Ping
    
    try:
        asyncio.run(main()) # 3. 啟動機器人
    except KeyboardInterrupt:
        print("機器人已關閉")

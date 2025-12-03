import discord
import os
import asyncio
import logging
from discord.ext import commands
from dotenv import load_dotenv
from keep_alive import keep_alive, auto_ping

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# 設定 Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 設定權限
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

# 🔥 關鍵修正 1：加上 help_command=None
# 這會關閉 Discord 醜醜的預設選單，讓您的 cogs/help.py 能夠生效 (支援 !h)
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    # 建議在啟動後載入 Cogs
    await load_cogs()
    logger.info(f"【{bot.user} 已上線】曼巴時刻啟動！")

async def load_cogs():
    if os.path.exists("./cogs"):
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                try:
                    await bot.load_extension(f"cogs.{filename[:-3]}")
                    logger.info(f"✅ 載入模組: {filename}")
                except Exception as e:
                    logger.error(f"❌ 無法載入 {filename}: {e}")

async def main():
    if not TOKEN:
        logger.error("錯誤：找不到 TOKEN，請檢查環境變數！")
        return
        
    async with bot:
        # 啟動網頁伺服器 (Keep Alive)
        keep_alive()
        auto_ping()
        
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from keep_alive import keep_alive  # 匯入網頁伺服器功能

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# ==========================================
# 核心設定：關閉預設 Help，開啟所有權限
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
# ==========================================

@bot.event
async def on_ready():
    print(f'機器人 {bot.user} 已登入！')
    print('------')

async def load_extensions():
    # 載入 cogs 資料夾裡的所有模組
    if os.path.exists('./cogs'):
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await bot.load_extension(f'cogs.{filename[:-3]}')
                except Exception as e:
                    print(f'無法載入 {filename}: {e}')
    else:
        print("找不到 cogs 資料夾，跳過載入模組。")

async def main():
    async with bot:
        keep_alive()  # 啟動網頁伺服器 (保持 Render 運作)
        await load_extensions()
        
        if not TOKEN:
            print("錯誤：找不到 Token，請檢查 Render 環境變數！")
            return
            
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

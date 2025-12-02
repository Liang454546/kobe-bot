import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from keep_alive import keep_alive  # 匯入網頁伺服器功能

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# ==========================================
# 👇 您之前可能不小心刪掉的部分 (定義 bot) 👇
intents = discord.Intents.all()
# 加入 help_command=None 以關閉預設的醜介面
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
# ==========================================

@bot.event
async def on_ready():
    print(f'機器人 {bot.user} 已登入！')
    print('------')

async def load_extensions():
    # 確保 cogs 資料夾存在
    if os.path.exists('./cogs'):
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                await bot.load_extension(f'cogs.{filename[:-3]}')
    else:
        print("找不到 cogs 資料夾，跳過載入模組。")

async def main():
    async with bot:
        keep_alive()  # 啟動網頁伺服器 (騙過 Render)
        await load_extensions()
        
        # 檢查 Token 是否存在
        if not TOKEN:
            print("錯誤：找不到 Token，請檢查 Render 環境變數！")
            return
            
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


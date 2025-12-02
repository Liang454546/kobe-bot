import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv

# 載入 .env 中的 Token
load_dotenv()
TOKEN = os.getenv('MTQ0NTAxMTAwNTQ1NjUxNTA4OA.G9zyGz.qQwCId7TALvlE_A_JJ1nvq-kl73OktuGKi7NMU')

# 設定意圖 (Intents) - 因為是小伺服器，我們全開
intents = discord.Intents.all()

# 設定指令前綴，例如 !help
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'機器人 {bot.user} 已登入！')
    print('------')

async def load_extensions():
    # 載入 cogs 資料夾內的檔案
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')

async def main():
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 處理 Ctrl+C 結束
        pass


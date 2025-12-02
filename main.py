import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv

# 1. 匯入剛剛寫的 keep_alive
from keep_alive import keep_alive 

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# ... (中間的程式碼都不用動) ...

async def main():
    async with bot:
        # 2. 在啟動機器人之前，先啟動小網站
        keep_alive() 
        
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

import discord
import os
import asyncio
import logging  # 新增：log
from discord.ext import commands
from dotenv import load_dotenv
from keep_alive import keep_alive  # 匯入網頁伺服器 (防 Render sleep)

# 載入 .env
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# ==========================================
# 核心設定：logging + intents (加 message_content)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

intents = discord.Intents.all()
intents.message_content = True  # 修：新版需，on_message 監聽
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
# ==========================================

@bot.event
async def on_ready():
    logger.info(f'機器人 {bot.user} 已登入！伺服器數：{len(bot.guilds)}')
    logger.info('曼巴訓練營啟動：準備點名軟蛋們！')
    print('------')  # 保留 print 給 console

# 新增：錯誤處理 (cog 載入 fail)
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # 忽略未知指令
    logger.error(f'指令錯誤: {error}')
    await ctx.send('指令出錯？軟蛋，檢查你的輸入！😤')

# 載入 cogs (加重載支援)
async def load_extensions():
    if not os.path.exists('./cogs'):
        logger.warning("找不到 cogs 資料夾，跳過載入。")
        return
    
    loaded = 0
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and not filename.startswith('__'):
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                loaded += 1
                logger.info(f'載入 cog: {filename}')
            except Exception as e:
                logger.error(f'無法載入 {filename}: {e}')
    
    logger.info(f'總共載入 {loaded} 個 cogs (game, daily, help, voice 等)。')
    if loaded == 0:
        logger.warning('無 cogs 載入？檢查資料夾！')

# 新增：重載指令 (開發用)
@bot.command(name='reload')
@commands.is_owner()  # 只 owner
async def reload_cog(ctx, cog_name: str):
    try:
        await bot.reload_extension(f'cogs.{cog_name}')
        await ctx.send(f'重載 {cog_name} 成功！Mamba 升級中... 🐍')
        logger.info(f'重載 {cog_name}')
    except Exception as e:
        await ctx.send(f'重載失敗: {e}')
        logger.error(f'重載 {cog_name} 失敗: {e}')

async def main():
    # 啟動 keep_alive (移前：thread 非阻塞)
    keep_alive()
    logger.info('Keep Alive 啟動：Bot 不會睡死！')
    
    # 載入 cogs
    await load_extensions()
    
    if not TOKEN:
        logger.error("錯誤：找不到 DISCORD_TOKEN，請檢查 .env 或 Render 環境變數！")
        return  # 修：不啟動 bot
    
    try:
        await bot.start(TOKEN)
    except Exception as e:
        logger.error(f'Bot 啟動失敗: {e}')
    finally:
        logger.info('Bot 關閉：Mamba Out. 🎤')

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('手動關閉 bot。')
    except Exception as e:
        logger.error(f'程式錯誤: {e}')

import discord
from discord.ext import commands
import os
import logging  # 新增：log
from flask import Flask  # 確保 import
from threading import Thread

# ... (你的 bot 設定、cogs load 等邏輯，這裡省略)

# Keep Alive 模組（升級版）
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)  # 修：用 __name__

@app.route('/')
def home():
    return "🏀 Kobe Bot is alive! Mamba Out. 🐍"

def run_flask():
    try:
        port = int(os.environ.get('PORT', 5000))  # 修：Heroku 彈性 port
        app.run(host='0.0.0.0', port=port, debug=False)  # 修：debug=False，避 log 刷
        logger.info(f"Flask 啟動於 port {port}")
    except Exception as e:
        logger.error(f"Flask 啟動失敗: {e}")
        # 可加 retry 或 exit

def keep_alive():
    t = Thread(target=run_flask, daemon=True)  # 新增：daemon=True，bot 關時跟關
    t.start()
    logger.info("Keep Alive 啟動：Bot 不會睡死！")

# ... (bot = commands.Bot(...); bot.load_extension('cogs.game') 等)

# bot.run('TOKEN')  # 你的 token

# 啟動 keep_alive（放 bot.run() 後）
keep_alive()

import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta, timezone
import random
import os
import google.generativeai as genai
from PIL import Image
import io
import aiohttp
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        self.active_sessions = {}
        self.cooldowns = {}
        self.cooldown_locks = asyncio.Lock()
        
        # 關鍵字庫
        self.weak_words = ["累", "想睡", "放棄", "休息", "好累", "睡了"]
        self.strong_words = ["健身", "訓練", "加班", "努力", "衝", "練"]
        self.kobe_quotes = [
            "Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍",
            "Soft. 🥚", "你見過洛杉磯凌晨四點嗎？"
        ]

        # === AI 初始化 (Gemini 1.5 Flash) ===
        self.model = None
        self.has_ai = False
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                self.has_ai = True
                logger.info("✅ Gemini 1.5 Flash 啟動成功")
            except Exception as e:
                logger.error(f"Gemini 初始化失敗: {e}")
        
    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.commit()
        self.daily_tasks.start()

    async def cog_unload(self):
        self.daily_tasks.cancel()

    # === AI 核心 ===
    async def ask_kobe(self, prompt, user_id=None):
        if not self.has_ai: return random.choice(self.kobe_quotes)
        
        # 冷卻檢查 (每人 5 秒)
        if user_id:
            now = time.time()
            if now - self.cooldowns.get(user_id, 0) < 5: return None
            self.cooldowns[user_id] = now

        try:
            sys = "你是 Kobe Bryant。語氣毒舌、嚴格。繁體中文(台灣)。30字內，多 emoji 🏀🐍。"
            response = await asyncio.to_thread(self.model.generate_content, [sys, prompt])
            return response.text.strip()
        except: return None

    # === 監聽訊息 (已移除 process_commands) ===
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # 1. 觸發 AI 回覆 (Mention 或 ? 結尾)
        is_reply = self.bot.user in message.mentions or message.content.strip().endswith("?")
        if is_reply:
            async with message.channel.typing():
                reply = await self.ask_kobe(f"用戶說：{message.content}", message.author.id)
                if reply: 
                    await message.reply(reply)
                else: 
                    # 冷卻中或錯誤時，不回話或回備用
                    pass 
            return # 處理完 AI 就結束，不往下執行

        # 2. 關鍵字偵測 (榮譽系統)
        if any(w in message.content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤 (榮譽 -2)")
            await self.update_stat(message.author.id, "lazy_points", 2)
        elif any(w in message.content for w in self.strong_words):
            await message.channel.send(f"{message.author.mention} 這才是曼巴精神！🏀 (榮譽 +2)")

        # ⚠️ 注意：這裡已經移除了 await self.bot.process_commands(message)
        # 這樣就不會導致指令被執行兩次

    # ... (保留您的其他指令 !rank, !focus 等) ...
    # 為了版面整潔，請保留您原本的 command 函式，只需替換上面的 on_message 邏輯

    @tasks.loop(hours=24)
    async def daily_tasks(self):
        pass # 每日任務邏輯

    async def update_stat(self, user_id, column, value):
        # 簡易資料庫更新
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
            await db.execute(f"UPDATE daily_stats SET {column} = {column} + ? WHERE user_id = ?", (value, user_id))
            await db.commit()

async def setup(bot):
    await bot.add_cog(Game(bot))

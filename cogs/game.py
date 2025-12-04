import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta, timezone
import random
import os
import io
import aiohttp
import logging
from PIL import Image
from collections import deque  # 加用於 processed_msg_ids

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        self.active_sessions = {}
        self.pending_replies = {}
        self.processed_msg_ids = deque(maxlen=1000)  # 自動淘汰
        self.last_spotify_roast = {} 
        self.short_term_memory = {} 
        self.last_chat_time = {} 
        
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.status_cooldowns = {}
        self.image_cooldowns = {}
        self.spotify_cooldowns = {} 
        
        api_key = os.getenv("GEMINI_API_KEY")
        self.has_ai = True if api_key else False

        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.toxic_words = ["幹", "靠", "爛", "輸"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍", "Soft. 🥚"]

        self.sys_prompt_template = (
            "你是 Kobe Bryant。個性：溫馨 真實、不恭維、專業、現實、專注於問題。\n"
            "1. **對話**：如果這是連續對話，請參考前文回答。\n"
            "2. **音樂審判**：你是心理學大師，透過音樂分析心理狀態。\n"
            "3. **錯字/邏輯/廢話**：嚴厲糾正。\n"
            "4. 繁體中文(台灣)，30字內，多用 emoji (🏀🐍)。"
        )

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.executescript('''
                CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE, PRIMARY KEY(user_id, game_name));
                CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE);
                CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE);
                CREATE TABLE IF NOT EXISTS chat_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, content TEXT, timestamp REAL);
                CREATE TABLE IF NOT EXISTS music_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, artist TEXT, timestamp REAL);
                CREATE INDEX IF NOT EXISTS idx_chat_timestamp ON chat_logs(timestamp);
                CREATE INDEX IF NOT EXISTS idx_music_timestamp ON music_history(timestamp);
            ''')
            await db.commit()
        
        self.daily_tasks.start()
        self.game_check.start()
        self.voice_check.start()
        self.ghost_check.start()
        await self.bot.wait_until_ready()

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.game_check.cancel()
        self.voice_check.cancel()
        self.ghost_check.cancel()

    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None, use_memory=False):
        if not hasattr(self.bot, 'ai_model') or not self.bot.ai_model: return None
        now = time.time()
        
        if user_id and cooldown_dict:
            async with self.cooldown_locks:  # 加鎖
                if now - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
                cooldown_dict[user_id] = now

        try:
            contents = []
            if use_memory and user_id:
                if now - self.last_chat_time.get(user_id, 0) > 600:
                    self.short_term_memory[user_id] = []
                self.last_chat_time[user_id] = now

                history = self.short_term_memory.get(user_id, [])
                if not history:
                    history.append({'role': 'user', 'parts': [self.sys_prompt_template]})
                    history.append({'role': 'model', 'parts': ["收到。"]})
                
                contents = list(history)
                user_msg = {'role': 'user', 'parts': [f"情境/用戶說：{prompt}"]}
                if image: user_msg['parts'].append(image)
                contents.append(user_msg)
            else:
                contents = [self.sys_prompt_template, f"情境/用戶說：{prompt}"]
                if image: contents.append(image)

            response = await asyncio.to_thread(self.bot.ai_model.generate_content, contents=contents)
            reply_text = response.text.strip()

            if use_memory and user_id and not image:
                self.short_term_memory.setdefault(user_id, [])
                if not self.short_term_memory[user_id]:
                     self.short_term_memory[user_id].append({'role': 'user', 'parts': [self.sys_prompt_template]})
                     self.short_term_memory[user_id].append({'role': 'model', 'parts': ["收到。"]})
                self.short_term_memory[user_id].append({'role': 'user', 'parts': [f"情境/用戶說：{prompt}"]})
                self.short_term_memory[user_id].append({'role': 'model', 'parts': [reply_text]})
                if len(self.short_term_memory[user_id]) > 22:
                    self.short_term_memory[user_id] = self.short_term_memory[user_id][-22:]  # 簡化截斷

            return reply_text
        except Exception as e:
            if "429" in str(e): return "⚠️ AI 額度滿了 (Rate Limit)，請稍候。"
            if "404" in str(e): return "⚠️ 模型更新中，請重啟 bot。"
            logger.error(f"AI 錯誤: {e}") 
            return "ERROR"

    # 監控邏輯（略，同原版...）

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        channel = self.get_text_channel(after.guild)
        
        # 遊戲
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game and not old_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            prompt = f"用戶開始玩 {new_game}。" + ("痛罵他玩2K是垃圾" if

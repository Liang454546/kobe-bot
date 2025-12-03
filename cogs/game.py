import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta, timezone
import random
import os
import google.generativeai as genai

class KobeBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "kobe_bot.db"
        self.active_game_sessions = {}
        self.game_times = {} 
        
        # 冷卻與計數器
        self.cooldowns = {}
        self.last_message_time = {}
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.chat_activity = []
        
        # --- 1. 設定 AI (Gemini Pro - 最穩定) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                # 🔥 修正為最穩定的 gemini-pro
                self.model = genai.GenerativeModel("gemini-pro")
                self.has_ai = True
                print("✅ Gemini Pro (穩定版) 啟動成功")
            except Exception as e:
                print(f"❌ AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        # 關鍵字庫 (已簡化)
        self.weak_words = ["累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。", "Soft. 🥚"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS daily_stats (
                    user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, 
                    game_seconds INTEGER DEFAULT 0, last_updated DATE
                )
            ''')
            await db.commit()
        # 啟動自動任務
        self.game_check.start()
        self.daily_tasks.start()
        self.random_mood.start()

    async def cog_unload(self):
        self.game_check.cancel()
        self.daily_tasks.cancel()
        self.random_mood.cancel()

    # ==========================================
    # 🧠 AI 核心
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30):
        if not self.has_ai: return None

        # 冷卻檢查
        if cooldown_dict and user_id and time.time() - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
        if cooldown_dict and user_id: cooldown_dict[user_id] = time.time()

        try:
            sys_prompt = "你是 Kobe Bryant，語氣毒舌、嚴格。請用繁體中文回答，50字內。"
            response = await asyncio.to_thread(self.model.generate_content, contents=[sys_prompt, prompt])
            return response.text
        except: return None

    # ==========================================
    # 🎯 遊戲時間偵測與毒舌
    # ==========================================
    @tasks.loop(minutes=1)
    async def game_check(self):
        # 檢查遊戲時間過長並公審的邏輯 (原樣保留)
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot: continue
                game = next((a.name for a in member.activities if a.type == discord.ActivityType.playing), None)
                if game:
                    now = time.time()
                    user_id = member.id
                    start = self.active_game_sessions.get(user_id, now)
                    self.active_game_sessions[user_id] = start
                    played_seconds = now - start + self.game_times.get(user_id, 0)
                    self.game_times[user_id] = played_seconds
                    
                    if played_seconds >= 3600 and (user_id not in self.cooldowns or now - self.cooldowns[user_id] > 1800):
                        channel = self.get_text_channel(guild)
                        if channel:
                            msg = await self.ask_kobe(f"用戶玩 {game} 超過 1 小時，罵他眼神還亮嗎？", user_id, self.cooldowns, 1800)
                            if msg:
                                await channel.send(f"⚠️ {member.mention} {msg}")
                                await self.update_stat(user_id, "lazy_points", 5)

    # ==========================================
    # 💬 聊天訊息監控 (修復雙重回應)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        user_id = message.author.id
        now = time.time()

        # 確保指令可以優先處理 (如果訊息以 '!' 開頭，直接跳過 passive 監聽)
        if message.content.startswith('!'):
            await self.bot.process_commands(message)
            return

        # 1. AI 對話 (被標記或提問)
        is_mentioned = self.bot.user in message.mentions or message.content.strip().endswith("?")
        
        if is_mentioned:
            # 使用更嚴格的 5 秒冷卻
            if user_id in self.cooldowns and now - self.cooldowns[user_id] < 5:
                await message.reply("別吵我，正在訓練。🏀 (冷卻中)")
                return

            reply = await self.ask_kobe(f"用戶問：{message.content}", user_id, self.cooldowns, 5)
            
            if reply:
                await message.reply(reply[:200])
            else:
                # 最終備用
                await message.reply(random.choice(self.kobe_quotes))
            return

        # 2. 榮譽偵測 (只保留最簡單的判斷，避免重複程式碼)
        if any(w in message.content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.update_stat(user_id, "lazy_points", 2)


    # ==========================================
    # 資料庫工具 (保持原樣)
    # ==========================================
    async def update_stat(self, user_id, column, value):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM daily_stats WHERE user_id = ?", (user_id,))
            if not await cursor.fetchone():
                await db.execute("INSERT INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
            await db.execute(f"UPDATE daily_stats SET {column} = {column} + ? WHERE user_id = ?", (value, user_id))
            await db.commit()

    def get_broadcast_channel(self):
        if not self.bot.guilds: return None
        guild = self.bot.guilds[0]
        return self.get_text_channel(guild)

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target), guild.text_channels) or guild.text_channels[0]

async def setup(bot):
    await bot.add_cog(KobeBot(bot))

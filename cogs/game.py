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
        self.focus_sessions = {}
        self.user_goals = {}
        self.voice_sessions = {}
        
        # 冷卻與計數器
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        
        # 🔥 新增：聊天熱度計數器 (用於自動插話)
        self.chat_timestamps = [] 
        
        # --- AI 設定 (Gemini 2.0 Flash) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (高互動模式)")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        # 關鍵字庫
        self.weak_words = ["累", "好累", "想睡", "放棄", "休息", "不想動"]
        self.strong_words = ["健身", "訓練", "加班", "努力", "寫扣", "唸書"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍", "Soft. 🥚"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.executescript('''
                CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE, PRIMARY KEY(user_id, game_name));
                CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE);
                CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE);
            ''')
            await db.commit()
        
        self.daily_tasks.start()
        self.game_check.start()
        self.voice_check.start()

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.game_check.cancel()
        self.voice_check.cancel()

    # ==========================================
    # 🧠 AI 核心：教練模式
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        # 冷卻檢查
        now = time.time()
        if user_id and cooldown_dict:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
            cooldown_dict[user_id] = now

        try:
            # 人設：教練模式
            sys_prompt = (
                "你是 Kobe Bryant。個性：毒舌、嚴格、極度痛恨懶惰，但尊重渴望變強的人。\n"
                "1. **問問題**：給出專業且實用的指導，但語氣要嚴厲。\n"
                "2. **偷懶/藉口**：(例如說累、想放棄) 狠狠罵他，用激將法叫他去訓練。\n"
                "3. **提到 NBA 2K**：暴怒，那是電子垃圾。\n"
                "4. 繁體中文(台灣)，50字內，多用 emoji (🏀🐍)。"
            )
            contents = [sys_prompt, f"用戶輸入：{prompt}"]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except Exception as e:
            logger.error(f"AI 呼叫錯誤: {e}") 
            return "ERROR"

    # ==========================================
    # 💬 聊天監控 (高互動 + AI 罵人)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # 0. 指令優先：如果是指令 (!)，直接略過，讓 main.py 處理 (防止雙重回應)
        if message.content.startswith('!'): return

        user_id = message.author.id
        content = message.content
        now = time.time()

        # 1. 🔥 自動插話 (Chat Burst)
        # 邏輯：如果 60 秒內有 10 則訊息，Bot 有機率插話
        self.chat_timestamps.append(now)
        self.chat_timestamps = [t for t in self.chat_timestamps if now - t < 60] # 只保留60秒內的紀錄
        
        if len(self.chat_timestamps) >= 10:
            if random.random() < 0.2: # 20% 機率插話
                self.chat_timestamps = [] # 重置計數
                async with message.channel.typing():
                    roast = await self.ask_kobe("群組聊天太熱烈了。毒舌插話：'你們有手指打字，沒力氣訓練？'")
                    if roast and roast not in ["COOLDOWN", "ERROR"]:
                        await message.channel.send(roast)

        # 2. AI 對話 (被標記 或 ? 結尾)
        is_mentioned = self.bot.user in message.mentions or (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user) or message.content.strip().endswith("?")
        
        if is_mentioned:
            async with message.channel.typing():
                # 縮短對話冷卻到 3 秒，讓互動更流暢
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 3)

                if reply == "COOLDOWN":
                    # 冷卻時不回話，或回個 emoji
                    await message.add_reaction("🏀") 
                elif reply == "ERROR":
                    await message.reply("⚠️ AI 連線錯誤。")
                elif reply:
                    await message.reply(reply)
                else:
                    await message.reply(random.choice(self.kobe_quotes))
            return

        # 3. 🔥 AI 藉口粉碎機 (取代舊版固定回應)
        if any(w in content for w in self.weak_words):
            async with message.channel.typing():
                # 讓 AI 生成罵人的話，而不是用固定的
                roast = await self.ask_kobe(f"用戶說：'{content}'。他在找藉口。用最毒舌的方式罵醒他！", user_id, self.ai_chat_cooldowns, 10)
                if roast and roast not in ["COOLDOWN", "ERROR"]:
                    await message.reply(roast)
                    await self.update_daily_stats(user_id, "lazy_points", 2)
            return

        # 4. 正向鼓勵 (維持固定，省資源)
        if any(w in content for w in self.strong_words):
            await message.channel.send(f"{message.author.mention} 這才是曼巴精神！🏀")
            await self.add_honor(user_id, 2)

    # ==========================================
    # 🎯 遊戲監控 (維持原樣)
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)
        channel = self.get_text_channel(after.guild)
        now = time.time()
        
        if user_id in self.cooldowns and now - self.cooldowns.get(user_id, 0) < 2: return
        self.cooldowns[user_id] = now 

        if new_game and not old_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            prompt = f"這軟蛋開始玩 {new_game} 了。" + ("痛罵他玩2K" if "2k" in new_game.lower() else "罵他不去訓練")
            roast = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            if channel: await channel.send(roast or f"{after.mention} 玩 **{new_game}**？不用唸書嗎？😡")

        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                if duration > 600 and channel:
                    interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘 {old_game}。質問他。", user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN": await channel.send(f"🎤 **賽後採訪** {after.mention}\n{interview}")

    # ==========================================
    # 資料庫與工具
    # ==========================================
    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 10: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    async def update_daily_stats(self, user_id, column, value):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM daily_stats WHERE user_id = ?", (user_id,))
            if not await cursor.fetchone():
                await db.execute("INSERT INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
            await db.execute(f"UPDATE daily_stats SET {column} = {column} + ? WHERE user_id = ?", (value, user_id))
            await db.commit()

    async def add_honor(self, user_id, amount):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (user_id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target) and x.permissions_for(guild.me).send_messages, guild.text_channels) or guild.text_channels[0]
    
    # ... (遊戲時間監控 task 保持不變) ...
    @tasks.loop(minutes=1)
    async def game_check(self):
        now = time.time()
        for user_id, session in list(self.active_sessions.items()):
            duration = int(now - session["start"])
            if duration >= 3600 and not session.get("1h_warned"):
                session["1h_warned"] = True
                await self.send_warning(user_id, session["game"], "1小時", 5)
            if duration >= 7200 and not session.get("2h_warned"):
                session["2h_warned"] = True
                await self.send_warning(user_id, session["game"], "2小時", 10)

    async def send_warning(self, user_id, game, time_str, penalty):
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild:
            member = guild.get_member(user_id)
            channel = self.get_text_channel(guild)
            if member and channel:
                msg = await self.ask_kobe(f"用戶玩 {game} 超過 {time_str}，罵他眼睛瞎了嗎") or f"{member.mention} {time_str}了！眼睛不乾嗎？"
                await channel.send(f"⚠️ **{time_str} 警報** {member.mention}\n{msg}")
                await self.update_daily_stats(user_id, "lazy_points", penalty)

    @tasks.loop(hours=24)
    async def daily_tasks(self): pass
    @tasks.loop(minutes=30)
    async def random_mood(self): pass
    @tasks.loop(seconds=30)
    async def voice_check(self): pass
    
    @game_check.before_loop
    @daily_tasks.before_loop
    @random_mood.before_loop
    @voice_check.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

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
        self.last_message_time = {}
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        
        # --- 1. 設定 AI (Gemini 2.0 Flash) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                # 使用最新 gemini-2.0-flash
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            logger.warning("⚠️ GEMINI_API_KEY 缺失，AI 備用模式")
            self.has_ai = False

        # 關鍵字庫
        self.weak_words = ["累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍", "Soft. 🥚"]
        self.procrastination_words = ["等下", "明天", "之後", "先休息", "再看", "晚點"]
        self.liar_keywords = ["讀書", "寫作業", "健身", "忙", "加班"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.executescript('''
                CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE, PRIMARY KEY(user_id, game_name));
                CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE);
                CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE);
            ''')
            await db.commit()
        
        # 啟動自動任務
        self.daily_tasks.start()
        self.game_check.start()
        self.random_mood.start()
        self.voice_check.start()

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.game_check.cancel()
        self.random_mood.cancel()
        self.voice_check.cancel()

    # ==========================================
    # AI 核心：通用問答 (修正參數與回傳)
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        # 冷卻檢查
        now = time.time()
        if user_id and cooldown_dict:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
            cooldown_dict[user_id] = now

        try:
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格。請用繁體中文(台灣)。回答簡短有力(30字內)，多用 emoji (🏀🐍)。"
            contents = [sys_prompt, f"情境：{prompt}"]
            if image: contents.append(image)
            
            # 使用 to_thread 避免阻塞，且呼叫 generate_content
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except Exception as e:
            logger.error(f"AI 呼叫錯誤: {e}") 
            return "ERROR"

    # ==========================================
    # 🎯 遊戲與狀態監控
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)
        channel = self.get_text_channel(after.guild)

        # 避免 Discord 瞬間多次更新
        now = time.time()
        if user_id in self.cooldowns and now - self.cooldowns.get(user_id, 0) < 2: return
        self.cooldowns[user_id] = now 

        if new_game == old_game: 
            # 偵測遊戲時間過長
            if new_game and user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                ROAST_THRESHOLD, ROAST_COOLDOWN = 7200, 21600 # 2小時 / 6小時冷卻
                
                if duration >= ROAST_THRESHOLD and (user_id not in self.ai_roast_cooldowns or now - self.ai_roast_cooldowns.get(user_id, 0) >= ROAST_COOLDOWN):
                    self.ai_roast_cooldowns[user_id] = now
                    hours = duration // 3600
                    prompt = f"這軟蛋玩 {new_game} 超過 {hours} 小時了。問他眼神還亮嗎？"
                    roast_msg = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 0)
                    if roast_msg and roast_msg not in ["COOLDOWN", "ERROR"]:
                        if channel:
                            await channel.send(f"⚠️ **疲勞警告！** {after.mention}\n{roast_msg}")
                            await self.update_daily_stats(user_id, "lazy_points", 10)
            return

        # 遊戲結束 (存檔 + 採訪)
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                
                if duration > 600 and channel:
                    mins = duration // 60
                    prompt = f"{after.display_name} 玩了 {mins} 分鐘 {old_game}。質問他學到了什麼？"
                    interview = await self.ask_kobe(prompt, user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview not in ["COOLDOWN", "ERROR"]: 
                        await channel.send(f"🎤 **賽後毒舌採訪** {after.mention}\n{interview}")

        # 遊戲開始 (AI 罵人)
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # AI 罵人 (冷卻 5 分鐘)
            roast_msg = await self.ask_kobe(f"這軟蛋開始玩 {new_game} 了，罵他。", user_id, self.ai_roast_cooldowns, 300)
            
            # 如果 AI 失敗，用備用
            if not roast_msg or roast_msg in ["COOLDOWN", "ERROR"]:
                roast_text = "不用唸書嗎？😡"
                roast_msg = f"{after.mention} {roast_text}"
            
            if channel: await channel.send(roast_msg)
            
            # 語音突襲 (無聲版)
            if after.voice and after.voice.channel:
                try:
                    vc = after.guild.voice_client
                    if not vc: await after.voice.channel.connect()
                    elif vc.channel != after.voice.channel: await vc.move_to(after.voice.channel)
                    if channel: await channel.send(f"🎙️ **語音查哨中...** (盯著你)")
                except: pass

    # ==========================================
    # 💬 聊天監控 (修復靜音 + 指令處理)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        user_id = message.author.id
        content = message.content
        
        # 1. AI 對話 (被標記)
        is_mentioned = self.bot.user in message.mentions or (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user)
        
        if is_mentioned:
            async with message.channel.typing():
                # 🔥 修正：傳入正確的 user_id, cooldown_dict, cooldown_time
                reply = await self.ask_kobe(f"用戶說：{content}", user_id, self.ai_chat_cooldowns, 5)

                if reply == "COOLDOWN":
                    await message.reply("別吵我，正在訓練。🏀 (冷卻中)")
                elif reply == "ERROR":
                    await message.reply("⚠️ AI 連線錯誤，請檢查 Render Logs 或 API Key。")
                elif reply:
                    await message.reply(reply)
                else:
                    # 終極備用 (當 AI 失敗時)
                    await message.reply(random.choice(self.kobe_quotes))
            return

        # 2. 關鍵字/藉口粉碎 (為了簡潔，這裡只保留最基本的判斷)
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.update_daily_stats(user_id, "lazy_points", 2) # 使用正確的 update function
        elif any(w in content for w in self.strong_words):
            await message.channel.send(f"{message.author.mention} 這才是曼巴精神！🏀")
            await self.add_honor(user_id, 2)
            
        # 🔥 關鍵：將控制權交還給指令處理器
        await self.bot.process_commands(message)

    # ==========================================
    # 資料庫與工具
    # ==========================================
    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today)) # 使用 REPLACE 避免主鍵衝突
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
    
    def get_broadcast_channel(self, guild=None):
        if not guild and self.bot.guilds: guild = self.bot.guilds[0]
        if not guild: return None
        return self.get_text_channel(guild)

    # ==========================================
    # Tasks (每日任務, etc)
    # ==========================================
    @tasks.loop(hours=24)
    async def daily_tasks(self):
        # 這裡可以放每日結算邏輯
        pass

    @tasks.loop(minutes=5)
    async def game_check(self):
        # 這裡可以放主動檢查遊戲時間的邏輯，如果 on_presence_update 已經處理了，這裡可以留空或做其他檢查
        pass

    @tasks.loop(minutes=30)
    async def random_mood(self):
        channel = self.get_broadcast_channel()
        if channel and random.random() < 0.3:
            await channel.send(random.choice([
                "誰在偷懶？🐍", "Mamba never quits.", "還不快去訓練？🏀",
                "我怎麼聞到軟蛋的味道？🥚"
            ]))

    @tasks.loop(seconds=30)
    async def voice_check(self):
        # 語音檢查邏輯
        pass
    
    @daily_tasks.before_loop
    @game_check.before_loop
    @random_mood.before_loop
    @voice_check.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

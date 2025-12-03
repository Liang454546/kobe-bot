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
import aiohttp  # 新增：圖片下載
import logging  # 新增：錯誤 log

# 設定 log
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
        
        # 冷卻與計數器（新增鎖定）
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()  # 簡化鎖
        self.last_message_time = {}
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        
        # --- 1. 設定 AI (Gemini Pro - 穩定版，改 vision) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-pro-vision")  # 修：支援圖片
                self.has_ai = True
                print("✅ Gemini Pro Vision 啟動成功")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            print("⚠️ 警告：找不到 GEMINI_API_KEY")
            self.has_ai = False

        # 關鍵字庫（修：加 emoji）
        self.weak_words = ["累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍", "Soft. 🥚"]
        self.procrastination_words = ["等下", "明天", "之後", "先休息", "再看", "晚點"]
        self.liar_keywords = ["讀書", "寫作業", "健身", "忙", "加班"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE)')
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

    # 新增：更新每日統計
    async def update_daily_stats(self, user_id, key, increment=1):
        async with aiosqlite.connect(self.db_name) as db:
            now = datetime.now(timezone.utc).date()
            await db.execute('''
                INSERT OR IGNORE INTO daily_stats (user_id, msg_count, lazy_points, roasted_count, last_updated)
                VALUES (?, 0, 0, 0, ?)
            ''', (user_id, now))
            await db.execute(f'UPDATE daily_stats SET {key} = {key} + ? WHERE user_id = ? AND last_updated = ?', (increment, user_id, now))
            await db.commit()

    # ==========================================
    # AI 核心：通用問答 (修：加鎖、log、emoji)
    # ==========================================
    async def ask_kobe(self, prompt, user_id=0, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        now = time.time()
        # 檢查冷卻（加鎖）
        async with self.cooldown_locks:
            if cooldown_dict and user_id and now - cooldown_dict.get(user_id, 0) < cooldown_time: return None
            if cooldown_dict and user_id: cooldown_dict[user_id] = now

        try:
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格。請用繁體中文(台灣)。回答簡短有力(30字內)，多用 emoji (🏀🐍)。"
            contents = [sys_prompt, prompt]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except Exception as e:
            logger.error(f"AI 生成失敗: {e}")
            return None

    # 新增：圖片分析（用 Gemini Vision）
    async def analyze_image(self, image_url, user_id):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    img_data = await resp.read()
                    image = Image.open(io.BytesIO(img_data))
                    img_part = genai.upload_file(image)  # Gemini upload
            
            prompt = "分析這張圖，判斷用戶是否在偷懶（e.g., 睡覺、玩遊戲）。毒舌回饋，用繁體中文。"
            reply = await self.ask_kobe(prompt, user_id, self.image_cooldowns, 60, img_part)
            return reply or "這圖太軟了！😤 去訓練吧。🏀"
        except Exception as e:
            logger.error(f"圖片分析失敗: {e}")
            return random.choice(self.kobe_quotes)

    # ==========================================
    # 遊戲與狀態監控（修：加 DB 存檔、語音連線）
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)
        channel = self.get_broadcast_channel(after.guild)  # 修：用 guild

        if new_game == old_game: return

        # 遊戲結束 (存檔 + 採訪)
        if old_game and user_id in self.active_sessions:
            start_time = self.active_sessions.pop(user_id)
            duration = int(time.time() - start_time)
            
            # 修：存到 DB
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute('INSERT INTO playtime (user_id, game_name, seconds, last_played) VALUES (?, ?, ?, ?)',
                                 (user_id, old_game, duration, datetime.now(timezone.utc).date()))
                await db.commit()
            
            # 修：更新 daily_stats
            await self.update_daily_stats(user_id, 'lazy_points', duration // 60)

            if duration > 600 and channel:
                prompt = f"{after.display_name} 玩了 {duration // 60} 分鐘 {old_game}。質問他學到了什麼？"
                interview = await self.ask_kobe(prompt, user_id, self.cooldowns, 0)
                if interview: await channel.send(f"🎤 賽後毒舌採訪 {after.mention}\n{interview}")

        # 遊戲開始 (AI 罵人)
        if new_game:
            self.active_sessions[user_id] = time.time()
            
            # AI 罵人 (用專用 cooldown)
            roast_msg = await self.ask_kobe(f"這軟蛋開始玩 {new_game} 了，罵他。", user_id, self.ai_roast_cooldowns, 300)
            
            if not roast_msg:
                roast_msg = random.choice(self.kobe_quotes)
            
            if channel: await channel.send(f"{after.mention} {roast_msg}")
            
            # 修：語音連線
            if after.voice and after.voice.channel:
                try:
                    vc = await after.voice.channel.connect()
                    self.voice_sessions[user_id] = {'vc': vc, 'last_audio': time.time()}
                except Exception as e:
                    logger.error(f"語音連線失敗: {e}")

    # ==========================================
    # 聊天監控（修：不早 return，加圖片、lower content）
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        user_id = message.author.id
        content = message.content.lower()  # 修：case-insensitive
        
        # 1. AI 對話
        is_mentioned = self.bot.user in message.mentions or message.content.strip().endswith("?")
        
        if is_mentioned:
            async with message.channel.typing():
                reply = await self.ask_kobe(f"用戶問：{message.content}", user_id, self.ai_chat_cooldowns, 10)  # 修：專用 cooldown
                if reply:
                    await message.reply(reply)
                else:
                    await message.reply(random.choice(self.kobe_quotes))
                # 修：不 return，讓指令繼續

        # 2. 圖片審判（修：實作）
        if message.attachments:
            attachment = message.attachments[0]
            if attachment.content_type and attachment.content_type.startswith('image/'):
                reply = await self.analyze_image(attachment.url, user_id)
                await message.reply(reply)
                await self.update_daily_stats(user_id, 'roasted_count', 1)
                return  # 圖片後可 return，避免重複

        # 3. 關鍵字粉碎（修：加 procrastination）
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.update_daily_stats(user_id, 'lazy_points', 1)
        elif any(w in content for w in self.procrastination_words):
            await message.channel.send(f"{message.author.mention} 等下？Mamba 現在就行動！🏀")

        # 4. 交還控制權
        await self.bot.process_commands(message)

    # ==========================================
    # 任務與工具（修：補齊邏輯）
    # ==========================================
    @tasks.loop(minutes=60)
    async def random_mood(self):
        channel = self.get_broadcast_channel(self.bot.guilds[0] if self.bot.guilds else None)
        if channel:
            await channel.send(random.choice(self.kobe_quotes))
    
    @tasks.loop(hours=1)  # 修：改小時，避免過頻
    async def daily_tasks(self):
        now = datetime.now(timezone.utc)
        if now.hour == 0:  # 午夜結算
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute('UPDATE daily_stats SET msg_count=0, lazy_points=0, roasted_count=0, last_updated=?', (now.date(),))
                await db.commit()
            channel = self.get_broadcast_channel(self.bot.guilds[0] if self.bot.guilds else None)
            if channel:
                challenge = random.choice(["今天健身 30 分！🏀", "別玩遊戲，讀書去！📚"])
                await channel.send(f"🗓️ 每日 Mamba 挑戰：{challenge}")

    @tasks.loop(minutes=5)
    async def voice_check(self):
        for user_id, session in list(self.voice_sessions.items()):
            vc = session.get('vc')
            if vc and vc.is_connected():
                if time.time() - session.get('last_audio', 0) > 300:  # 5分無音
                    member = self.bot.get_user(user_id)
                    if member and member.voice:
                        await member.voice.channel.send(f"{member.mention} 語音擺爛？說話啊！🐍")
                    await vc.disconnect()
                    del self.voice_sessions[user_id]

    # 新增：game_check（監控 focus）
    @tasks.loop(minutes=10)
    async def game_check(self):
        for user_id, end_time in list(self.focus_sessions.items()):
            if time.time() > end_time:
                del self.focus_sessions[user_id]
                # 加懲罰：e.g., + lazy_points

    def get_broadcast_channel(self, guild=None):
        if not guild and self.bot.guilds: guild = self.bot.guilds[0]
        if not guild: return None
        return self.get_text_channel(guild)

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target), guild.text_channels) or guild.text_channels[0]

async def setup(bot):
    await bot.add_cog(Game(bot))

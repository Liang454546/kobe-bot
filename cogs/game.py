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
        
        # 狀態儲存
        self.active_sessions = {}
        self.pending_replies = {}
        
        # 冷卻系統
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.status_cooldowns = {}
        self.image_cooldowns = {}
        self.spotify_cooldowns = {} 
        
        # --- AI 設定 ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (音樂偵測修復版)")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        # 關鍵字庫
        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.toxic_words = ["幹", "靠", "爛", "輸"]
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
        self.ghost_check.start()

        # 啟動時掃描遊戲
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot: continue
                game = next((a.name for a in member.activities if a.type == discord.ActivityType.playing), None)
                if game and member.id not in self.active_sessions:
                    self.active_sessions[member.id] = {"game": game, "start": time.time(), "1h_warned": False, "2h_warned": False}

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.game_check.cancel()
        self.voice_check.cancel()
        self.ghost_check.cancel()

    # ==========================================
    # 🧠 AI 核心
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None
        now = time.time()
        if user_id and cooldown_dict:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
            cooldown_dict[user_id] = now

        try:
            sys_prompt = (
                "你是 Kobe Bryant。個性：毒舌、嚴格、偏執於細節。\n"
                "1. **音樂審判**：如果是軟綿綿的歌(情歌/流行)，罵他軟蛋；如果是硬派(搖滾/嘻哈)，稱讚節奏。\n"
                "2. **錯字/邏輯**：嚴厲糾正。\n"
                "3. **團隊意識**：罵已讀不回的人。\n"
                "4. 繁體中文(台灣)，50字內，多用 emoji (🏀🐍)。"
            )
            contents = [sys_prompt, f"情境：{prompt}"]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except Exception as e:
            logger.error(f"AI 錯誤: {e}") 
            return "ERROR"

    # ==========================================
    # 🎯 狀態監控 (重點修復區)
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        channel = self.get_text_channel(after.guild)
        
        # 1. 遊戲偵測
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game and not old_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            prompt = f"用戶開始玩 {new_game}。" + ("痛罵他玩2K" if "2k" in new_game.lower() else "罵他不去訓練")
            roast = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            if channel: await channel.send(f"{after.mention} {roast or f'玩 {new_game}？去訓練！'}")

        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                if duration > 600 and channel:
                    interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘 {old_game}。質問收穫。", user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN": await channel.send(f"🎤 **賽後採訪** {after.mention}\n{interview}")

        # 2. 🔥 音樂偵測 (Spotify 品味審判)
        new_spotify = next((a for a in after.activities if isinstance(a, discord.Spotify)), None)
        old_spotify = next((a for a in before.activities if isinstance(a, discord.Spotify)), None)
        
        # 如果偵測到 Spotify
        if new_spotify:
            # 檢查是否換歌了，或是剛開始聽
            is_new_track = not old_spotify or new_spotify.track_id != old_spotify.track_id
            
            if is_new_track:
                logger.info(f"🎵 偵測到音樂: {after.display_name} - {new_spotify.title}")
                
                # 🔥 這裡把機率改成 100% (原本是 < 0.2)，方便您測試
                # 測試成功後，如果您覺得太吵，可以把下方 1.0 改回 0.2
                if random.random() < 1.0: 
                    prompt = f"用戶正在聽 Spotify: {new_spotify.title} - {new_spotify.artist}。判斷這首歌是否夠硬派(HipHop/Rock)。如果是情歌/K-Pop/抖音歌，罵他軟蛋；如果是硬的，給予肯定。"
                    
                    # 這裡設 60 秒冷卻 (原本 600)，方便測試換歌
                    roast = await self.ask_kobe(prompt, user_id, self.spotify_cooldowns, 60) 
                    
                    if channel and roast and roast != "COOLDOWN":
                        await channel.send(f"🎵 **DJ Mamba 點評** {after.mention}\n{roast}")

    # ==========================================
    # 🔍 狀態查詢指令 (Debug 用)
    # ==========================================
    @commands.command(aliases=["st", "狀況"])
    async def status(self, ctx):
        """查看全服即時狀態 (含詳細 Spotify 資訊)"""
        embed = discord.Embed(title="📊 曼巴監控中心", color=0x2ecc71)
        count = 0
        for member in ctx.guild.members:
            if member.bot: continue 
            activities = []
            for act in member.activities:
                if act.type == discord.ActivityType.playing:
                    activities.append(f"🎮 {act.name}")
                elif act.type == discord.ActivityType.streaming:
                    activities.append(f"📹 直播")
                elif isinstance(act, discord.Spotify):
                    # 🔥 特別顯示正在聽什麼，確認 Bot 有讀到
                    activities.append(f"🎵 **{act.title}** ({act.artist})")
                elif act.type == discord.ActivityType.listening:
                    activities.append(f"🎵 聽歌: {act.name}")

            stat_str = "🟢" if member.status == discord.Status.online else "⚫"
            desc = ", ".join(activities) if activities else "💤 休息"
            embed.add_field(name=f"{stat_str} {member.display_name}", value=desc, inline=False)
            count += 1
        embed.set_footer(text=f"監控 {count} 人 | 若沒看到歌名，請檢查 Discord 設定")
        await ctx.send(embed=embed)

    # ==========================================
    # 💬 聊天監控
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.content.startswith('!'): return 

        user_id = message.author.id
        content = message.content.strip()
        
        # A. 已讀不回解除
        if user_id in self.pending_replies: del self.pending_replies[user_id]

        # B. 註冊已讀不回
        if message.mentions:
            for member in message.mentions:
                if not member.bot and member.status == discord.Status.online and member.id != user_id:
                    self.pending_replies[member.id] = {'time': time.time(), 'channel': message.channel, 'mention_by': message.author}

        # 1. AI 對話
        is_question = content.endswith(("?", "？"))
        is_mentioned = self.bot.user in message.mentions
        if is_mentioned or is_question:
            async with message.channel.typing():
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 3)
                await message.reply(reply or random.choice(self.kobe_quotes))
            return

        # 2. 負能量
        if any(w in content for w in self.toxic_words):
            async with message.channel.typing():
                roast = await self.ask_kobe(f"用戶說：'{content}'。他在散播失敗主義。狠狠罵他。", user_id, self.ai_chat_cooldowns, 30)
                if roast and roast != "COOLDOWN": await message.reply(roast)
            return

        # 3. 細節糾察 (20% 機率)
        if len(content) > 10 and random.random() < 0.2:
            async with message.channel.typing():
                roast = await self.ask_kobe(f"檢查這句話有無錯字邏輯：'{content}'。若無錯回傳 PASS。", user_id, {}, 0)
                if roast and "PASS" not in roast and roast != "COOLDOWN" and roast != "ERROR":
                    await message.reply(f"📝 **細節糾察**\n{roast}")
            return

        # 4. 關鍵字
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            
        await self.bot.process_commands(message)

    # ... (Helper Functions) ...
    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''INSERT INTO playtime (user_id, game_name, seconds, last_played) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, game_name) DO UPDATE SET seconds = seconds + excluded.seconds, last_played = excluded.last_played''', (user_id, game_name, seconds, today))
            await db.commit()

    async def update_daily_stats(self, user_id, column, value):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM daily_stats WHERE user_id = ?", (user_id,))
            if not await cursor.fetchone(): await db.execute("INSERT INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
            await db.execute(f"UPDATE daily_stats SET {column} = {column} + ? WHERE user_id = ?", (value, user_id))
            await db.commit()

    async def add_honor(self, user_id, amount):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (user_id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    def get_text_channel(self, guild):
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in ["chat", "general", "聊天", "公頻"]) and x.permissions_for(guild.me).send_messages, guild.text_channels) or guild.text_channels[0]

    # ... (Tasks) ...
    @tasks.loop(minutes=1)
    async def ghost_check(self):
        now = time.time()
        for uid, data in list(self.pending_replies.items()):
            if now - data['time'] > 600:
                channel, author = data['channel'], data['mention_by']
                member = channel.guild.get_member(uid)
                if member and member.status == discord.Status.online:
                    msg = await self.ask_kobe(f"隊友 {author.display_name} 傳球給 {member.display_name} 10分鐘不回。罵他。", uid, {}, 0)
                    if msg: await channel.send(f"💤 **無視傳球** {member.mention}\n{msg}")
                del self.pending_replies[uid]

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
                msg = await self.ask_kobe(f"用戶玩 {game} 超過 {time_str}，罵他眼睛瞎了嗎", user_id, {}, 0) or f"{member.mention} {time_str}了！"
                await channel.send(f"⚠️ **{time_str} 警報** {member.mention}\n{msg}")
                await self.update_daily_stats(user_id, "lazy_points", penalty)

    @commands.command(aliases=['r'])
    async def rank(self, ctx):
        # (Rank 程式碼同上版，為節省空間省略，請保留)
        pass

    @tasks.loop(hours=24)
    async def daily_tasks(self): pass
    @tasks.loop(seconds=60)
    async def voice_check(self): pass
    
    @game_check.before_loop
    @daily_tasks.before_loop
    @voice_check.before_loop
    @ghost_check.before_loop
    async def before_loops(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

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
        
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        
        # --- AI 設定 ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "尼哥別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強尼哥。🐍", "Soft. 🥚"]

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
        
        # 啟動時掃描現有遊戲
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot: continue
                game = next((a.name for a in member.activities if a.type == discord.ActivityType.playing), None)
                if game and member.id not in self.active_sessions:
                    self.active_sessions[member.id] = {
                        "game": game, "start": time.time(), "1h_warned": False, "2h_warned": False
                    }

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.game_check.cancel()
        self.voice_check.cancel()

    # ==========================================
    # 🔥 修復：Rank 指令 (必須在 Class 內)
    # ==========================================
    @commands.command(aliases=['r'])
    async def rank(self, ctx):
        """查看遊戲時長排行榜"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT user_id, SUM(seconds) as total FROM playtime GROUP BY user_id')
            rows = await cursor.fetchall()
            
        stats = {row[0]: row[1] for row in rows}
        now = time.time()
        # 加上正在玩的時長
        for uid, session in self.active_sessions.items():
            current_duration = int(now - session['start'])
            stats[uid] = stats.get(uid, 0) + current_duration

        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

        if not sorted_stats:
            return await ctx.send("📊 目前沒有遊戲紀錄！")

        embed = discord.Embed(title="🏆 偷懶黑鬼尼哥遊戲時長排行榜 再玩要被當光光了", color=0xffd700)
        desc = ""
        for i, (uid, seconds) in enumerate(sorted_stats):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"用戶({uid})"
            status_icon = "🎮" if uid in self.active_sessions else ""
            desc += f"**{i+1}. {name}** {status_icon}\n   └ {seconds//3600}小時 {(seconds%3600)//60}分\n"

        embed.description = desc
        await ctx.send(embed=embed)

    # ==========================================
    # 🔥 新增功能：!status (!狀況)
    # ==========================================
    @commands.command(aliases=["st", "狀況"])
    async def status(self, ctx):
        """查看全服即時狀態"""
        guild = ctx.guild
        embed = discord.Embed(
            title="📊 曼巴監控中心",
            description=f"時間: {datetime.now().strftime('%H:%M')}",
            color=0x2ecc71
        )
        
        count = 0
        for member in guild.members:
            if member.bot: continue 
            activities = []
            for act in member.activities:
                if act.type == discord.ActivityType.playing:
                    activities.append(f"🎮 {act.name}")
                elif act.type == discord.ActivityType.streaming:
                    activities.append(f"📹 直播: {act.name}")
                elif act.type == discord.ActivityType.listening:
                    activities.append(f"🎵 聽歌")

            stat_str = "🟢" if member.status == discord.Status.online else "⚫"
            desc = ", ".join(activities) if activities else "💤 休息中"
            
            embed.add_field(name=f"{stat_str} {member.display_name}", value=desc, inline=False)
            count += 1
            
        embed.set_footer(text=f"監控 {count} 人")
        await ctx.send(embed=embed)

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
            sys_prompt = "你是 Kobe Bryant。有梗 語氣祥和、專業。教練模式：回答問題要專業，簡答 。繁體中文(台灣)。"
            response = await asyncio.to_thread(self.model.generate_content, contents=[sys_prompt, f"用戶：{prompt}"])
            return response.text
        except: return None

    # ==========================================
    # 🎯 監控邏輯
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
            roast = await self.ask_kobe(f"這尼哥開始玩 {new_game} 了，罵他。", user_id, self.ai_roast_cooldowns, 300)
            if channel: await channel.send(roast or f"{after.mention} 玩 **{new_game}**？不用唸書嗎？😡")

        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                if duration > 600 and channel:
                    interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘。質問他。", user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN": await channel.send(f"🎤 **賽後採訪** {after.mention}\n{interview}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        # 0. 指令優先：如果是指令 (!)，直接略過
        if message.content.startswith('!'): return 

        is_mentioned = self.bot.user in message.mentions or message.content.strip().endswith("?")
        if is_mentioned:
            async with message.channel.typing():
                reply = await self.ask_kobe(message.content, message.author.id, self.ai_chat_cooldowns, 5)
                await message.reply(reply or random.choice(self.kobe_quotes))
            return

        if any(w in message.content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？尼哥！😤")
            await self.update_daily_stats(message.author.id, "lazy_points", 2)
            
        await self.bot.process_commands(message)

    # ... (Helper Functions) ...
    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 10: return 
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                INSERT INTO playtime (user_id, game_name, seconds, last_played) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, game_name) DO UPDATE SET seconds = seconds + excluded.seconds, last_played = excluded.last_played
            ''', (user_id, game_name, seconds, today))
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

    # ... (Tasks: game_check, daily_tasks, voice_check 等保持不變) ...
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


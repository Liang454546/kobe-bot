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
        self.voice_sessions = {}
        
        # 🔥 新增：已讀不回偵測 {user_id: {'time': timestamp, 'channel': channel_obj, 'mention_by': author}}
        self.pending_replies = {}
        
        # 冷卻系統
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.status_cooldowns = {}
        self.image_cooldowns = {}
        self.spotify_cooldowns = {} # 🎵 Spotify 冷卻
        
        # --- AI 設定 ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (全方位監控版)")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        # 關鍵字庫
        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.toxic_words = ["幹", "靠", "爛", "輸"] # 😡 負能量關鍵字
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
        self.ghost_check.start() # 🔥 啟動已讀不回偵測

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
                "你是 Kobe Bryant。個性：毒舌、嚴格、偏執於細節、痛恨失敗主義。\n"
                "1. **音樂審判**：如果是軟綿綿的歌，罵他軟蛋；如果是硬派的，稱讚節奏。\n"
                "2. **錯字/邏輯**：如同糾正投籃姿勢一樣，嚴厲糾正他的錯誤。\n"
                "3. **無視隊友**：隊友傳球(tag)不接？罵他沒團隊意識。\n"
                "4. **負能量**：聽到抱怨/髒話，罵他閉嘴去檢討自己。\n"
                "5. 繁體中文(台灣)，50字內，多用 emoji (🏀🐍)。"
            )
            contents = [sys_prompt, f"情境：{prompt}"]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except Exception as e:
            logger.error(f"AI 錯誤: {e}") 
            return "ERROR"

    # ==========================================
    # 🎯 狀態監控 (遊戲 + 🎵 Spotify)
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        channel = self.get_text_channel(after.guild)
        now = time.time()
        
        # 1. 遊戲偵測 (維持原樣)
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

        # 2. 🔥 新增：Spotify 品味審判 (DJ Mamba)
        new_spotify = next((a for a in after.activities if isinstance(a, discord.Spotify)), None)
        old_spotify = next((a for a in before.activities if isinstance(a, discord.Spotify)), None)
        
        # 如果換歌了，或者剛開始聽
        if new_spotify and (not old_spotify or new_spotify.track_id != old_spotify.track_id):
            # 只有 20% 機率觸發，避免每首歌都罵
            if random.random() < 0.2:
                prompt = f"用戶正在聽 Spotify: {new_spotify.title} - {new_spotify.artist}。判斷這首歌是否夠硬派(HipHop/Rock)。如果是情歌/K-Pop，罵他軟；如果是硬的，給予肯定。"
                roast = await self.ask_kobe(prompt, user_id, self.spotify_cooldowns, 600) # 10分鐘冷卻
                if channel and roast and roast != "COOLDOWN":
                    await channel.send(f"🎵 **DJ Mamba 點評** {after.mention}\n{roast}")

    # ==========================================
    # 💬 聊天監控 (錯字/已讀不回/負能量)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.content.startswith('!'): return 

        user_id = message.author.id
        content = message.content.strip()
        
        # 🔥 A. 解除已讀不回狀態
        # 如果這個人說話了，就從 pending 名單移除
        if user_id in self.pending_replies:
            del self.pending_replies[user_id]

        # 🔥 B. 註冊已讀不回 (Ghosting Tracker)
        if message.mentions:
            for member in message.mentions:
                if not member.bot and member.status == discord.Status.online and member.id != user_id:
                    # 記錄被 Tag 的人，開始計時
                    self.pending_replies[member.id] = {
                        'time': time.time(),
                        'channel': message.channel,
                        'mention_by': message.author
                    }

        # 1. AI 對話
        is_question = content.endswith(("?", "？"))
        is_mentioned = self.bot.user in message.mentions
        
        if is_mentioned or is_question:
            async with message.channel.typing():
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 3)
                if reply == "COOLDOWN": await message.add_reaction("🕒")
                elif reply == "ERROR": await message.reply("⚠️ AI 連線錯誤。")
                elif reply: await message.reply(reply)
                else: await message.reply(random.choice(self.kobe_quotes))
            return

        # 🔥 2. 負能量偵測 (Toxic Spreader)
        if any(w in content for w in self.toxic_words):
            async with message.channel.typing():
                roast = await self.ask_kobe(f"用戶說：'{content}'。他在散播失敗主義。狠狠罵他閉嘴檢討自己。", user_id, self.ai_chat_cooldowns, 30)
                if roast and roast != "COOLDOWN":
                    await message.reply(roast)
                    await self.update_daily_stats(user_id, "lazy_points", 5) # 扣分
            return

        # 🔥 3. 細節糾察隊 (錯字/邏輯)
        # 條件：訊息長度 > 10 且 10% 機率觸發 (避免太煩)
        if len(content) > 10 and random.random() < 0.1:
            async with message.channel.typing():
                # 這裡不設 user cooldown，因為是隨機抽查
                roast = await self.ask_kobe(f"檢查這句話有沒有錯字或邏輯不通：'{content}'。如果有，嚴厲糾正；如果沒有，就回傳 'PASS'。", user_id, {}, 0)
                if roast and "PASS" not in roast and roast != "COOLDOWN" and roast != "ERROR":
                    await message.reply(f"📝 **細節糾察**\n{roast}")
            return

        # 4. 關鍵字 (藉口)
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.update_daily_stats(user_id, "lazy_points", 2)
            
        await self.bot.process_commands(message)

    # ==========================================
    # ⏰ 任務迴圈 (包含已讀不回檢查)
    # ==========================================
    
    # 🔥 新增：已讀不回檢查 (每分鐘)
    @tasks.loop(minutes=1)
    async def ghost_check(self):
        now = time.time()
        # 複製一份 keys 避免修改錯誤
        for uid, data in list(self.pending_replies.items()):
            # 檢查是否超過 10 分鐘 (600秒)
            if now - data['time'] > 600:
                channel = data['channel']
                author = data['mention_by']
                member = channel.guild.get_member(uid)
                
                # 再次確認狀態是否為線上
                if member and member.status == discord.Status.online:
                    msg = await self.ask_kobe(f"隊友 {author.display_name} 傳球(Tag)給 {member.display_name} 已經 10 分鐘了，但他明明線上卻不回。罵他無視團隊。", uid, {}, 0)
                    if msg:
                        await channel.send(f"💤 **無視傳球** {member.mention}\n{msg}")
                
                # 處罰完畢，移除名單
                del self.pending_replies[uid]

    # ... (其他 helper functions 與 tasks 維持原樣) ...
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

    @tasks.loop(seconds=60)
    async def voice_check(self):
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if member.bot: continue
                    if member.voice.self_mute:
                        if random.random() < 0.3:
                            channel = self.get_text_channel(guild)
                            if channel:
                                msg = await self.ask_kobe(f"{member.display_name} 在語音靜音。罵他。", user_id=member.id, cooldown_dict=self.status_cooldowns, cooldown_time=600)
                                if msg and msg != "COOLDOWN": await channel.send(f"🔇 **靜音糾察** {member.mention}\n{msg}")

    # !rank and !status commands (Assuming included)
    @commands.command(aliases=['r'])
    async def rank(self, ctx):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT user_id, SUM(seconds) as total FROM playtime GROUP BY user_id')
            rows = await cursor.fetchall()
        stats = {row[0]: row[1] for row in rows}
        now = time.time()
        for uid, session in self.active_sessions.items():
            stats[uid] = stats.get(uid, 0) + int(now - session['start'])
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
        if not sorted_stats: return await ctx.send("📊 無遊戲紀錄！")
        embed = discord.Embed(title="🏆 遊戲時長排行榜", color=0xffd700)
        desc = ""
        for i, (uid, seconds) in enumerate(sorted_stats):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"用戶({uid})"
            status = "🎮" if uid in self.active_sessions else ""
            desc += f"**{i+1}. {name}** {status}\n   └ {seconds//3600}小時 {(seconds%3600)//60}分\n"
        embed.description = desc
        await ctx.send(embed=embed)

    @commands.command(aliases=["st", "狀況"])
    async def status(self, ctx):
        embed = discord.Embed(title="📊 曼巴監控中心", color=0x2ecc71)
        for member in ctx.guild.members:
            if member.bot: continue 
            activities = []
            for act in member.activities:
                if act.type == discord.ActivityType.playing: activities.append(f"🎮 {act.name}")
                elif act.type == discord.ActivityType.streaming: activities.append(f"📹 直播")
                elif act.type == discord.ActivityType.listening: activities.append(f"🎵 聽歌")
            desc = ", ".join(activities) if activities else "💤 休息"
            stat_str = "🟢" if member.status == discord.Status.online else "⚫"
            embed.add_field(name=f"{stat_str} {member.display_name}", value=desc, inline=False)
        await ctx.send(embed=embed)

    @tasks.loop(hours=24)
    async def daily_tasks(self): pass
    
    @game_check.before_loop
    @daily_tasks.before_loop
    @voice_check.before_loop
    @ghost_check.before_loop
    async def before_loops(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

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
        self.status_cooldowns = {}
        self.image_cooldowns = {}
        
        # 🔥 新增：訊息計數器 (用於每 3 句按表情)
        self.msg_counter = {}
        
        # --- AI 設定 (Gemini 2.0 Flash) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (表情互動版)")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
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
        
        # 啟動時掃描
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

    # ==========================================
    # 🧠 AI 核心：教練模式
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        now = time.time()
        if user_id and cooldown_dict:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
            cooldown_dict[user_id] = now

        try:
            sys_prompt = (
                "你是 Kobe Bryant。個性：毒舌、嚴格、專業、痛恨失敗。\n"
                "1. **問問題**：專業且嚴厲地回答。\n"
                "2. **遊戲審判**：根據遊戲名稱，判斷這對籃球員是否有幫助 (通常沒有)，然後毒舌批評。\n"
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
    # 🎯 全自動偵測 (遊戲/直播/閒置)
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

        # A. 遊戲開始
        if new_game and not old_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            
            # AI 分析遊戲品味
            prompt = f"用戶開始玩 **{new_game}** 了。請根據這個遊戲名稱，毒舌點評他的品味和墮落程度。"
            if "2k" in new_game.lower(): prompt += " (特別強調痛恨 2K)"
            
            roast = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            if channel: await channel.send(f"{after.mention} {roast or f'又玩 {new_game}？去訓練！'}")

        # B. 遊戲結束 (只存檔與採訪)
        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                
                # 一般賽後採訪
                if duration > 600 and channel:
                    interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘 {old_game}。質問收穫。", user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN": 
                        await channel.send(f"🎤 **賽後採訪** {after.mention}\n{interview}")

        # C. 直播/閒置偵測
        new_stream = next((a for a in after.activities if a.type == discord.ActivityType.streaming), None)
        old_stream = next((a for a in before.activities if a.type == discord.ActivityType.streaming), None)
        if new_stream and not old_stream:
            roast = await self.ask_kobe(f"{after.display_name} 開直播。罵他不務正業。", user_id, self.status_cooldowns, 300)
            if channel and roast and roast != "COOLDOWN": await channel.send(f"📹 **直播糾察** {after.mention}\n{roast}")

        if before.status == discord.Status.online and after.status in [discord.Status.idle, discord.Status.invisible, discord.Status.dnd]:
            if random.random() < 0.3:
                roast = await self.ask_kobe(f"{after.display_name} 改狀態躲起來。罵他懦夫。", user_id, self.status_cooldowns, 600)
                if channel and roast and roast != "COOLDOWN": await channel.send(f"💤 **狀態警報** {after.mention}\n{roast}")

    # ==========================================
    # 💬 聊天監控 (每3句按表情)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.content.startswith('!'): return 

        user_id = message.author.id
        content = message.content.strip()
        
        # 🔥 新增功能：每 3 句自動按表情 (Rhythm Master)
        count = self.msg_counter.get(user_id, 0) + 1
        self.msg_counter[user_id] = count
        
        if count % 3 == 0:
            # 隨機挑選一個表情：包含 曼巴精神 vs 嘲諷
            emojis = ["🔥", "🏀", "🐍", "👀", "😤", "🤡", "💀", "👎", "💪", "💩"]
            try:
                await message.add_reaction(random.choice(emojis))
            except:
                pass # 如果沒權限或表情不存在就跳過

        # 1. AI 對話
        is_question = content.endswith(("?", "？"))
        is_mentioned = self.bot.user in message.mentions or (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user)
        
        if is_mentioned or is_question:
            async with message.channel.typing():
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 3)
                if reply == "COOLDOWN": await message.add_reaction("🕒")
                elif reply == "ERROR": await message.reply("⚠️ AI 連線錯誤。")
                elif reply: await message.reply(reply)
                else: await message.reply(random.choice(self.kobe_quotes))
            return

        # 2. 圖片審判
        if message.attachments:
            if any(message.attachments[0].content_type.startswith(t) for t in ["image/"]):
                async with message.channel.typing():
                    reply = await self.analyze_image(message.attachments[0].url, user_id)
                    await message.reply(reply)
                return

        # 3. 關鍵字
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.update_daily_stats(user_id, "lazy_points", 2)
        elif any(w in content for w in self.strong_words):
            await message.channel.send(f"{message.author.mention} 這才是曼巴精神！🏀")
            await self.add_honor(user_id, 2)
            
        await self.bot.process_commands(message)

    # ==========================================
    # 資料庫與工具
    # ==========================================
    async def analyze_image(self, image_url, user_id):
        async with self.cooldown_locks:
            now = time.time()
            if now - self.image_cooldowns.get(user_id, 0) < 60: return "冷卻中...🧘‍♂️"
            self.image_cooldowns[user_id] = now
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200: return "圖片錯誤。"
                    data = await resp.read()
            image = Image.open(io.BytesIO(data))
            reply = await self.ask_kobe("分析圖片。分類(食物/程式/遊戲)並毒舌點評。", user_id, {}, 0, image=image)
            return reply or "我看不到曼巴精神。🐍"
        except: return random.choice(self.kobe_quotes)

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

    @tasks.loop(hours=24)
    async def daily_tasks(self): pass
    
    @game_check.before_loop
    @daily_tasks.before_loop
    @voice_check.before_loop
    async def before_loops(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

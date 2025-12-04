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
        self.voice_sessions = {}
        
        # 對話監控專用
        self.last_msg_content = {} # {channel_id: "content"} 用來比對話題終結
        self.repeater_count = {}   # {user_id: {"content": "abc", "count": 1}}
        self.recent_messages = {}  # {message_id: {author: member, content: str, time: timestamp}} 用來抓刪文
        
        # 冷卻與計數器
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        self.status_cooldowns = {}
        
        # --- AI 設定 ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (對話糾察版)")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍", "Soft. 🥚"]
        
        # 話題終結者關鍵字
        self.killer_words = ["喔", "嗯", "恩", "真假", "哦", "= =", "...", "哈哈"]

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
                "你是 Kobe Bryant。個性：毒舌、嚴格、專業。\n"
                "1. **問問題**：給出專業且實用的指導，但語氣要嚴厲。\n"
                "2. **偷懶/藉口**：狠狠罵他。\n"
                "3. **刪文/敷衍**：嘲笑他心虛或沒團隊意識。\n"
                "4. 繁體中文(台灣)，50字內，多用 emoji (🏀🐍)。"
            )
            contents = [sys_prompt, f"用戶輸入：{prompt}"]
            if image: contents.append(image)
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except: return None

    # ==========================================
    # 💬 聊天監控 (四大功能整合)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.content.startswith('!'): return 

        user_id = message.author.id
        content = message.content.strip()
        channel_id = message.channel.id
        now = time.time()

        # 記錄訊息以便偵測刪文 (只存最近 5 分鐘)
        self.recent_messages[message.id] = {
            'author': message.author, 
            'content': content, 
            'time': now,
            'channel': message.channel
        }
        # 清理舊訊息
        clean_keys = [k for k, v in self.recent_messages.items() if now - v['time'] > 300]
        for k in clean_keys: del self.recent_messages[k]

        # 1. 🌅 凌晨四點俱樂部 (Early Bird)
        tz = timezone(timedelta(hours=8))
        local_now = datetime.now(tz)
        if 4 <= local_now.hour < 6:
            # 每天每人只觸發一次
            key = f"early_{user_id}_{local_now.date()}"
            if key not in self.cooldowns:
                self.cooldowns[key] = True
                await message.channel.send(f"🌅 {message.author.mention} 你醒了？很好。這就是洛杉磯凌晨四點的風景。致敬。🏀")

        # 2. 🧊 話題終結者 (Momentum Killer)
        last_content = self.last_msg_content.get(channel_id, "")
        # 如果上一句很長 (>10字)，且這句很短且是敷衍詞
        if len(last_content) > 10 and content in self.killer_words:
            roast = await self.ask_kobe(f"上一句大家聊很熱烈('{last_content}')，結果 {message.author.display_name} 只回了'{content}'。罵他把球氣洩光了。", user_id, self.ai_chat_cooldowns, 30)
            if roast and roast != "COOLDOWN":
                await message.reply(f"🧊 **話題終結者**\n{roast}")
        
        # 更新上一句紀錄
        self.last_msg_content[channel_id] = content

        # 3. ♻️ 復讀機殺手 (Repeater Penalty)
        user_repeat = self.repeater_count.get(user_id, {"content": "", "count": 0})
        if content == user_repeat["content"]:
            user_repeat["count"] += 1
        else:
            user_repeat = {"content": content, "count": 1}
        
        self.repeater_count[user_id] = user_repeat
        
        if user_repeat["count"] >= 3:
            # 重置計數以免一直罵
            self.repeater_count[user_id]["count"] = 0
            await message.reply(f"♻️ **復讀機犯規** {message.author.mention} 重複動作是為了訓練肌肉記憶，不是讓你像鸚鵡一樣刷頻！去訓練！")

        # 4. AI 對話 (被標記 或 ? 結尾)
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

        # 5. 圖片審判
        if message.attachments:
            if any(message.attachments[0].content_type.startswith(t) for t in ["image/"]):
                async with message.channel.typing():
                    reply = await self.analyze_image(message.attachments[0].url, user_id)
                    await message.reply(reply)
                return

        await self.bot.process_commands(message)

    # ==========================================
    # 🗑️ 刪文偵測 (Delete Shame)
    # ==========================================
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.id in self.recent_messages:
            data = self.recent_messages[message.id]
            # 如果是 10 秒內刪除的
            if time.time() - data['time'] < 10:
                roast = await self.ask_kobe(f"{data['author'].display_name} 剛發了訊息又秒刪。嘲笑他心虛，像投了麵包球想裝沒事。", data['author'].id, {}, 0)
                if roast and roast != "COOLDOWN":
                    await data['channel'].send(f"🗑️ **刪文抓包** {data['author'].mention}\n{roast}")
            
            del self.recent_messages[message.id]

    # ... (其他功能: analyze_image, save_to_db, tasks 等維持原樣) ...
    # 為了版面簡潔，以下省略重複的 helper functions，請務必保留原有的 database & tasks 程式碼
    
    async def analyze_image(self, image_url, user_id):
        # ... (同上版) ...
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
            await db.execute("INSERT OR REPLACE INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
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

    # ... (Tasks: game_check, daily_tasks, voice_check) ...
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        # ... (同上版，保留遊戲監控邏輯) ...
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
            if channel: await channel.send(f"{after.mention} {roast or '玩遊戲？不用唸書嗎？😡'}")

        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                if duration > 600 and channel:
                    interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘 {old_game}。質問他。", user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN": await channel.send(f"🎤 **賽後採訪** {after.mention}\n{interview}")

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
        pass # 這裡省略內容，請保留原有的語音監控

    # !rank and !status
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
    async def before_loops(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

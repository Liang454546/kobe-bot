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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔥 請確認這裡填入的是您的「指定頻道 ID」
TARGET_CHANNEL_ID = 1385233731073343498

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        
        # 狀態儲存
        self.active_sessions = {}
        self.pending_replies = {}
        self.processed_msg_ids = set() 
        self.last_spotify_roast = {} 
        self.short_term_memory = {} 
        self.last_chat_time = {} 
        self.last_music_processed = {}
        
        # 冷卻系統
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
            "你是 Kobe Bryant。個性：真實、不恭維、專業、現實、專注於問題。\n"
            "1. **回答問題**：針對用戶問題給予專業、嚴厲但實用的建議。**絕對不要硬扯籃球比喻**，除非真的很貼切。\n"
            "2. **對話**：如果這是連續對話，請參考前文回答。\n"
            "3. **音樂審判**：你是心理學大師，透過音樂分析心理狀態。要提及歌名。\n"
            "4. **錯字/邏輯**：嚴厲糾正。\n"
            "5. 繁體中文(台灣)，30字內，多用 emoji (🏀🐍)。"
        )

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.executescript('''
                CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE, PRIMARY KEY(user_id, game_name));
                CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE);
                CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE);
                CREATE TABLE IF NOT EXISTS chat_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, content TEXT, timestamp REAL);
                CREATE TABLE IF NOT EXISTS music_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, artist TEXT, timestamp REAL);
            ''')
            await db.commit()
        
        self.daily_tasks.start()
        self.game_check.start()
        # self.voice_check.start() # 🔥 已移除
        self.ghost_check.start()
        await self.bot.wait_until_ready()

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.game_check.cancel()
        # self.voice_check.cancel() # 🔥 已移除
        self.ghost_check.cancel()

    def get_text_channel(self, guild):
        channel = guild.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            return discord.utils.find(lambda x: any(t in x.name.lower() for t in ["chat", "general", "聊天", "公頻"]) and x.permissions_for(guild.me).send_messages, guild.text_channels) or guild.text_channels[0]
        return channel

    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None, use_memory=False):
        if not hasattr(self.bot, 'ai_model') or not self.bot.ai_model: return None
        now = time.time()
        
        if user_id and cooldown_dict:
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
                    self.short_term_memory[user_id] = self.short_term_memory[user_id][:2] + self.short_term_memory[user_id][-20:]

            return reply_text
        except Exception as e:
            if "429" in str(e): return "⚠️ AI 額度滿了 (Rate Limit)，請稍候。"
            logger.error(f"AI 錯誤: {e}") 
            return "ERROR"

    async def analyze_image(self, image_url, user_id):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200: return "圖片讀取失敗。"
                    data = await resp.read()
            image = Image.open(io.BytesIO(data))
            reply = await self.ask_kobe("分析這張圖片。分類(食物/程式/遊戲)並毒舌點評。", user_id, {}, 0, image=image, use_memory=False)
            return reply or "我看不到曼巴精神。🐍"
        except: return random.choice(self.kobe_quotes)

    # 狀態監控
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
            prompt = f"用戶開始玩 {new_game}。" + ("痛罵他玩2K是垃圾" if "2k" in new_game.lower() else "罵他不去訓練")
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

        # 2. 音樂偵測
        new_spotify = next((a for a in after.activities if isinstance(a, discord.Spotify)), None)
        old_spotify = next((a for a in before.activities if isinstance(a, discord.Spotify)), None)
        
        if new_spotify and (not old_spotify or new_spotify.track_id != old_spotify.track_id):
            if self.last_music_processed.get(user_id) == new_spotify.track_id: return 
            self.last_music_processed[user_id] = new_spotify.track_id
            
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("INSERT INTO music_history (user_id, title, artist, timestamp) VALUES (?, ?, ?, ?)", 
                                 (user_id, new_spotify.title, new_spotify.artist, time.time()))
                await db.commit()

            # 🔥 機率 20%
            if random.random() < 0.2: 
                prompt = f"用戶正在聽 Spotify: {new_spotify.title} - {new_spotify.artist}。請用心理學分析為什麼聽這首歌 以及分析歌詞與歌名 要提及歌名。"
                roast = await self.ask_kobe(prompt, user_id, {}, 0) 
                if channel and roast and "⚠️" not in str(roast) and roast != "COOLDOWN":
                    await channel.send(f"🎵 **DJ Mamba 點評** {after.mention}\n{roast}")

    # 聊天監控
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.content.startswith('!'): return 

        if message.id in self.processed_msg_ids: return
        self.processed_msg_ids.add(message.id)
        if len(self.processed_msg_ids) > 1000: self.processed_msg_ids.clear()

        user_id = message.author.id
        content = message.content.strip()
        
        if len(content) > 0:
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("INSERT INTO chat_logs (user_id, content, timestamp) VALUES (?, ?, ?)", (user_id, content, time.time()))
                if random.random() < 0.05:
                    limit_time = time.time() - 86400
                    await db.execute("DELETE FROM chat_logs WHERE timestamp < ?", (limit_time,))
                await db.commit()

        if user_id in self.pending_replies: del self.pending_replies[user_id]
        if message.mentions:
            for member in message.mentions:
                if not member.bot and member.status == discord.Status.online and member.id != user_id:
                    self.pending_replies[member.id] = {'time': time.time(), 'channel': message.channel, 'mention_by': message.author}

        is_question = content.endswith(("?", "？")) and len(content) > 1
        is_mentioned = self.bot.user in message.mentions
        has_image = message.attachments and any(message.attachments[0].content_type.startswith(t) for t in ["image/"])
        has_toxic = any(w in content for w in self.toxic_words)
        has_weak = any(w in content for w in self.weak_words)

        if has_image:
            if is_mentioned or random.random() < 0.1:
                async with message.channel.typing():
                    reply = await self.analyze_image(message.attachments[0].url, user_id)
                    await message.reply(reply)
            return

        elif is_mentioned or is_question:
            async with message.channel.typing():
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 3, use_memory=True)
                if reply == "COOLDOWN": await message.add_reaction("🕒")
                elif "⚠️" in str(reply): await message.reply("⚠️ AI 連線不穩")
                elif reply: await message.reply(reply)
            return

        elif has_toxic:
            async with message.channel.typing():
                roast = await self.ask_kobe(f"用戶說：'{content}'。他在散播失敗主義。狠狠罵他。", user_id, self.ai_chat_cooldowns, 30)
                if roast and "⚠️" not in str(roast) and roast != "COOLDOWN": await message.reply(roast)
            return

        elif len(content) > 10 and random.random() < 0.2:
            async with message.channel.typing():
                roast = await self.ask_kobe(f"檢查這句話有無錯字邏輯：'{content}'。若無錯回傳 PASS。", user_id, {}, 0)
                if roast and "PASS" not in roast and "⚠️" not in str(roast) and roast != "COOLDOWN":
                    await message.reply(f"📝 **細節糾察**\n{roast}")
            return

        elif has_weak:
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.update_daily_stats(user_id, "lazy_points", 2)
            
        await self.bot.process_commands(message)

    # ... Helper Functions ...
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

    # 指令區
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
        if not sorted_stats: return await ctx.send("📊 今天還沒人開始訓練！")
        embed = discord.Embed(title="📅 今日遊戲時長排行榜 (每日重置)", color=0xffd700)
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
                elif isinstance(act, discord.Spotify): activities.append(f"🎵 {act.title}")
                elif act.type == discord.ActivityType.listening: activities.append(f"🎵 聽歌")
            desc = ", ".join(activities) if activities else "💤 休息"
            stat_str = "🟢" if member.status == discord.Status.online else "⚫"
            embed.add_field(name=f"{stat_str} {member.display_name}", value=desc, inline=False)
        await ctx.send(embed=embed)

    @commands.command(aliases=["summary", "recap", "總結"])
    async def chat_summary(self, ctx):
        async with ctx.typing():
            async with aiosqlite.connect(self.db_name) as db:
                limit_time = time.time() - 43200 
                cursor = await db.execute("SELECT user_id, content FROM chat_logs WHERE timestamp > ? ORDER BY id DESC LIMIT 50", (limit_time,))
                rows = await cursor.fetchall()
            
            if not rows: return await ctx.send("最近沒人說話，球場一片死寂。")

            chat_text = ""
            for uid, content in reversed(rows):
                member = ctx.guild.get_member(uid)
                name = member.display_name if member else "有人"
                chat_text += f"{name}: {content}\n"

            prompt = f"以下是最近的對話紀錄，請總結重點，不要講廢話：\n\n{chat_text}"
            summary = await self.ask_kobe(prompt, ctx.author.id, {}, 0)

            if summary and "⚠️" not in str(summary):
                embed = discord.Embed(title="📋 戰術檢討會議", description=summary, color=0xe67e22)
                await ctx.send(embed=embed)
            else:
                await ctx.send("分析失敗。")

    @commands.command(aliases=["s", "songs", "音樂"])
    async def music_analysis(self, ctx):
        async with ctx.typing():
            async with aiosqlite.connect(self.db_name) as db:
                week_ago = time.time() - 604800
                cursor = await db.execute("SELECT DISTINCT title, artist FROM music_history WHERE user_id = ? AND timestamp > ? ORDER BY id DESC LIMIT 20", (ctx.author.id, week_ago))
                rows = await cursor.fetchall()

            if not rows: return await ctx.send(f"{ctx.author.mention} 這週沒有聽歌紀錄。")

            song_list = "\n".join([f"- {r[0]} by {r[1]}" for r in rows])
            prompt = f"這是用戶 {ctx.author.display_name} 這週聽的歌單：\n{song_list}\n請分析他的心理狀態。"
            analysis = await self.ask_kobe(prompt, ctx.author.id, {}, 0)

            if analysis and "⚠️" not in str(analysis):
                embed = discord.Embed(title=f"🎵 音樂心理分析：{ctx.author.display_name}", description=analysis, color=0x1db954)
                await ctx.send(embed=embed)
            else:
                await ctx.send("分析失敗。")

    @tasks.loop(hours=24)
    async def daily_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        if now.hour == 23 and now.minute == 59:
            channel = self.get_text_channel(self.bot.guilds[0]) if self.bot.guilds else None
            if not channel: return
            async with aiosqlite.connect(self.db_name) as db:
                limit = time.time() - 86400
                cursor = await db.execute("SELECT user_id, content FROM chat_logs WHERE timestamp > ? ORDER BY id DESC LIMIT 30", (limit,))
                chat_rows = await cursor.fetchall()
                cursor = await db.execute("SELECT user_id, lazy_points FROM daily_stats ORDER BY lazy_points DESC LIMIT 3")
                rows = await cursor.fetchall()

            report = []
            for row in rows:
                m = self.bot.get_user(row[0])
                name = m.display_name if m else f"用戶{row[0]}"
                report.append(f"- {name}: 懶惰指數 {row[1]}")
            
            chat_summary = "無"
            if chat_rows: chat_summary = "\n".join([f"{self.bot.get_user(u).display_name if self.bot.get_user(u) else u}: {c}" for u, c in chat_rows])

            prompt = f"違規名單：\n{chr(10).join(report)}\n\n對話紀錄：\n{chat_summary}\n\n請寫一篇曼巴毒舌日報。"
            news = await self.ask_kobe(prompt, 0, {}, 0)
            
            if "⚠️" not in str(news):
                embed = discord.Embed(title="📰 曼巴日報", description=news, color=0xe74c3c)
                await channel.send(embed=embed)

            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("DELETE FROM daily_stats")
                await db.execute("DELETE FROM playtime") # 🔥 清空每日遊戲時間
                await db.commit()
    
    @game_check.before_loop
    @daily_tasks.before_loop
    @ghost_check.before_loop
    async def before_loops(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

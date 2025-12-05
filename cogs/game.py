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
from collections import deque, Counter

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
        self.processed_msg_ids = deque(maxlen=2000)
        self.last_spotify_roast = {}
        self.short_term_memory = {}
        self.last_chat_time = {}
        self.last_music_processed = {}
        self.user_goals = {}
        
        # 任務執行標記
        self._morning_executed = None
        
        # 冷卻系統
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.status_cooldowns = {}
        self.image_cooldowns = {}
        self.spotify_cooldowns = {}
        self.detail_cooldowns = {}
        self.toxic_cooldowns = {}
        
        # 新功能所需變數
        self.long_term_memory = {}
        self.daily_question_asked = None
        self.daily_question_msg_id = None
        self.pending_daily_answer = set()
        self.daily_question_channel = None
        self.last_daily_summary = None
        self.daily_word_count = {}
        self.spotify_taste = {}
        
        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.toxic_words = ["幹", "靠", "爛", "輸"]
        self.nonsense_words = ["哈", "喔", "笑死", "恩", "4", "呵呵", "真假", "確實"]
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
                CREATE TABLE IF NOT EXISTS nonsense_stats (user_id INTEGER PRIMARY KEY, count INTEGER DEFAULT 0);
            ''')
            await db.commit()
        
        self.daily_tasks.start()
        self.weekly_tasks.start()
        self.game_check.start()
        self.ghost_check.start()
        self.morning_execution.start()
        self.daily_mamba_question.start()
        self.mood_radar.start()
        self.daily_summary_and_memory.start()
        await self.bot.wait_until_ready()

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.weekly_tasks.cancel()
        self.game_check.cancel()
        self.ghost_check.cancel()
        self.morning_execution.cancel()
        self.daily_mamba_question.cancel()
        self.mood_radar.cancel()
        self.daily_summary_and_memory.cancel()

    def get_text_channel(self, guild):
        if not guild: return None
        channel = guild.get_channel(TARGET_CHANNEL_ID)
        if channel and channel.permissions_for(guild.me).send_messages:
            return channel
        return discord.utils.find(
            lambda c: any(t in c.name.lower() for t in ["chat", "general", "聊天", "公頻"]) and c.permissions_for(guild.me).send_messages,
            guild.text_channels
        ) or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None, use_memory=False):
        if not hasattr(self.bot, 'ask_brain') or not self.bot.ask_brain:
            return None
            
        now = time.time()
        if user_id and cooldown_dict is not None:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time:
                return "COOLDOWN"
            cooldown_dict[user_id] = now

        try:
            final_prompt = f"情境/用戶說：{prompt}"
            history = None
            if use_memory and user_id:
                if now - self.last_chat_time.get(user_id, 0) > 600:
                    self.short_term_memory[user_id] = []
                self.last_chat_time[user_id] = now
                history = self.short_term_memory.get(user_id, [])
            reply_text = await self.bot.ask_brain(final_prompt, image=image, system_instruction=self.sys_prompt_template, history=history)
            if use_memory and user_id and not image and reply_text:
                self.short_term_memory.setdefault(user_id, [])
                self.short_term_memory[user_id].append({'role': 'user', 'parts': [final_prompt]})
                self.short_term_memory[user_id].append({'role': 'model', 'parts': [reply_text]})
                if len(self.short_term_memory[user_id]) > 10:
                    self.short_term_memory[user_id] = self.short_term_memory[user_id][-10:]
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
            reply = await self.ask_kobe("分析這張圖片。分類(食物/程式/遊戲)並毒舌點評。", user_id, self.image_cooldowns, 60, image=image, use_memory=False)
            return reply or "我看不到曼巴精神。🐍"
        except:
            return random.choice(self.kobe_quotes)

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        channel = self.get_text_channel(after.guild)
        if not channel: return

        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)
        if new_game and not old_game:
            if user_id in self.active_sessions:
                pass
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            prompt = f"用戶開始玩 {new_game}。" + ("痛罵他玩2K是垃圾" if "2k" in new_game.lower() else "罵他不去訓練")
            roast = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            if roast == "COOLDOWN": return
            msg = roast if (roast and roast != "ERROR") else f"玩 {new_game}？去訓練！"
            await channel.send(f"{after.mention} {msg}")
        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions.pop(user_id, None)
                if session:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    if duration > 600:
                        interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘 {old_game}。質問收穫。", user_id, self.ai_chat_cooldowns, 0)
                        if interview and interview != "COOLDOWN":
                            await channel.send(f"🎤 **賽後採訪** {after.mention}\n{interview}")

        new_spotify = next((a for a in after.activities if isinstance(a, discord.Spotify)), None)
        old_spotify = next((a for a in before.activities if isinstance(a, discord.Spotify)), None)
        
        if new_spotify and (not old_spotify or new_spotify.track_id != old_spotify.track_id):
            now = time.time()
            if now - self.last_music_processed.get(user_id, 0) < 10: return
            self.last_music_processed[user_id] = now
            
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("INSERT INTO music_history (user_id, title, artist, timestamp) VALUES (?, ?, ?, ?)",
                                 (user_id, new_spotify.title, new_spotify.artist, now))
                await db.commit()

            # Spotify 風格長期記憶
            title_art = (new_spotify.title + " " + new_spotify.artist).lower()
            mood_map = {
                "sad": ["哭", "雨", "分手", "夜", "slow", "ballad", "lonely", "miss"],
                "angry": ["fuck", "shit", "rage", "恨", "幹", "怒"],
                "chill": ["lofi", "chill", "relax", "study", "coffee"],
                "hype": ["gym", "workout", "rap", "rock", "hype", "pump"]
            }
            detected = "neutral"
            for mood, kws in mood_map.items():
                if any(k in title_art for k in kws):
                    detected = mood
                    break

            self.spotify_taste.setdefault(user_id, {"count": 0, "moods": {}})
            self.spotify_taste[user_id]["count"] += 1
            self.spotify_taste[user_id]["moods"][detected] = self.spotify_taste[user_id]["moods"].get(detected, 0) + 1
            
            if self.spotify_taste[user_id]["count"] % 15 == 0:
                total = sum(self.spotify_taste[user_id]["moods"].values())
                dominant = max(self.spotify_taste[user_id]["moods"], key=self.spotify_taste[user_id]["moods"].get)
                pct = self.spotify_taste[user_id]["moods"][dominant] / total * 100
                if pct > 65:
                    roast = await self.ask_kobe(
                        f"用戶最近 {pct:.0f}% 聽 {dominant} 類型歌（目前聽了{self.spotify_taste[user_id]['count']}首），分析他的心理狀態，要毒舌",
                        user_id, self.spotify_cooldowns, 300)
                    if roast and roast != "COOLDOWN":
                        await channel.send(f"🎵 **深度心理剖析** {after.mention}\n{roast}")

            if random.random() < 0.2:
                prompt = f"用戶正在聽 Spotify: {new_spotify.title} - {new_spotify.artist}。請用心理學分析品味。"
                roast = await self.ask_kobe(prompt, user_id, self.spotify_cooldowns, 180)
                if roast and roast != "COOLDOWN" and "⚠️" not in str(roast):
                    await channel.send(f"🎵 **DJ Mamba 點評** {after.mention}\n{roast}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.content.startswith('!'): return
        if message.id in self.processed_msg_ids: return
        self.processed_msg_ids.append(message.id)
        user_id = message.author.id
        content = message.content.strip()
        lower = content.lower()

        if len(content) > 0:
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("INSERT INTO chat_logs (user_id, content, timestamp) VALUES (?, ?, ?)", (user_id, content, time.time()))
                if random.random() < 0.05:
                    limit_time = time.time() - 86400
                    await db.execute("DELETE FROM chat_logs WHERE timestamp < ?", (limit_time,))
                await db.commit()

            # 每日詞頻統計
            self.daily_word_count[user_id] = self.daily_word_count.get(user_id, "") + " " + content

            # 黑歷史候選
            if any(w in lower for w in self.weak_words + ["廢", "爛", "不行", "放棄"]) or len(content) < 6:
                if random.random() < 0.1:
                    async with aiosqlite.connect(self.db_name) as db:
                        await db.execute("INSERT INTO chat_logs (user_id, content, timestamp) VALUES (?, ?, ?)", 
                                       (user_id, "[黑歷史]" + content, time.time()))

        if user_id in self.pending_replies: self.pending_replies.pop(user_id, None)
        if message.mentions:
            for member in message.mentions:
                if not member.bot and member.status == discord.Status.online and member.id != user_id:
                    self.pending_replies[member.id] = {'time': time.time(), 'channel': message.channel, 'mention_by': message.author}

        for word in self.nonsense_words:
            if word in content.lower():
                async with aiosqlite.connect(self.db_name) as db:
                    await db.execute("INSERT OR IGNORE INTO nonsense_stats (user_id, count) VALUES (?, 0)", (user_id,))
                    await db.execute("UPDATE nonsense_stats SET count = count + 1 WHERE user_id = ?", (user_id,))
                    await db.commit()
                break

        if random.random() < 0.3:
            emojis = ["🔥", "🏀", "🐍", "💪", "🤡", "💩", "💀", "👀"]
            try: await message.add_reaction(random.choice(emojis))
            except: pass

        is_question = content.endswith(("?", "？")) and len(content) > 1
        is_mentioned = self.bot.user in message.mentions
        has_image = message.attachments and any(att.content_type and att.content_type.startswith("image/") for att in message.attachments)
        has_toxic = any(w in content for w in self.toxic_words)
        has_weak = any(w in content for w in self.weak_words)

        # 說累自動 @ 最廢的人
        if any(w in lower for w in ["好累", "想睡", "睡了", "累死", "沒力", "廢了", "好睏"]):
            today = datetime.now().strftime("%Y-%m-%d")
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute("SELECT user_id, seconds FROM playtime WHERE last_played = ? ORDER BY seconds DESC LIMIT 1", (today,))
                row = await cursor.fetchone()
            if row and row[0] != user_id:
                loser = self.bot.get_user(row[0])
                if loser:
                    hours = row[1] // 3600
                    mins = (row[1] % 3600) // 60
                    await message.reply(f"{loser.mention} 你今天已經玩了 {hours}小時{mins}分還敢說累？\n你才是最廢的那個🐍")

        if has_image:
            if is_mentioned or random.random() < 0.1:
                async with message.channel.typing():
                    reply = await self.analyze_image(message.attachments[0].url, user_id)
                    await message.reply(reply)
            return

        elif is_mentioned or is_question:
            if is_mentioned:
                clean_text = content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
                if not clean_text and not is_question: return
            async with message.channel.typing():
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 3, use_memory=True)
                if reply == "COOLDOWN":
                    await message.add_reaction("🕒")
                    return
                elif reply and "⚠️" not in str(reply):
                    await message.reply(reply)
            return

        elif has_toxic:
            async with message.channel.typing():
                roast = await self.ask_kobe(f"用戶說：'{content}'。散播失敗主義。罵他。", user_id, self.toxic_cooldowns, 30)
                if roast and roast != "COOLDOWN" and "⚠️" not in str(roast):
                    await message.reply(roast)
            return

        elif len(content) > 10 and random.random() < 0.2:
            async with message.channel.typing():
                roast = await self.ask_kobe(f"檢查這句話有無錯字邏輯：'{content}'。若無錯回傳 PASS。", user_id, self.detail_cooldowns, 60)
                if roast and "PASS" not in roast and roast != "COOLDOWN" and "⚠️" not in str(roast):
                    await message.reply(f"📝 **細節糾察**\n{roast}")
            return

        elif has_weak:
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.update_daily_stats(user_id, "lazy_points", 2)

        await self.bot.process_commands(message)

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
            if not await cursor.fetchone():
                await db.execute("INSERT INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
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
            if now - data['time'] > 1800:
                self.pending_replies.pop(uid, None)
                continue
            if now - data['time'] > 600:
                channel = data['channel']
                if not channel:
                    self.pending_replies.pop(uid, None)
                    continue
                member = channel.guild.get_member(uid)
                if member and member.status == discord.Status.online:
                    msg = await self.ask_kobe(f"隊友 {data['mention_by'].display_name} 傳球給 {member.display_name} 10分鐘不回。罵他。", uid, {}, 0)
                    if msg:
                        await channel.send(f"💤 **無視傳球** {member.mention}\n{msg}")
                        await self.update_daily_stats(uid, "lazy_points", 5)
                self.pending_replies.pop(uid, None)

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
                msg = await self.ask_kobe(f"用戶玩 {game} 超過 {time_str}，罵他眼睛瞎了嗎", user_id, self.ai_roast_cooldowns, 300)
                if msg and msg != "COOLDOWN":
                    await channel.send(f"⚠️ **{time_str} 警報** {member.mention}\n{msg}")
                    await self.update_daily_stats(user_id, "lazy_points", penalty)

    @tasks.loop(hours=1)
    async def weekly_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        if now.weekday() == 6 and 20 <= now.hour < 21:
            if self._weekly_executed == now.strftime("%Y-%m-%d"): return
            self._weekly_executed = now.strftime("%Y-%m-%d")
            channel = self.get_text_channel(self.bot.guilds[0]) if self.bot.guilds else None
            if not channel: return
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute("SELECT user_id, count FROM nonsense_stats ORDER BY count DESC LIMIT 1")
                nonsense_row = await cursor.fetchone()
            if nonsense_row:
                m = self.bot.get_user(nonsense_row[0])
                name = m.display_name if m else f"User{nonsense_row[0]}"
                count = nonsense_row[1]
                await channel.send(f"🤡 **本週廢話王**：{m.mention if m else name} (發了 {count} 次廢話)\nKobe: 『你的幽默感跟你的投籃一樣廉價。』🐍")
                async with aiosqlite.connect(self.db_name) as db:
                    await db.execute("DELETE FROM nonsense_stats")
                    await db.commit()
            embed = discord.Embed(title="🗳️ 本週最廢表情符號投票", description="哪個表情最讓你火大？", color=0xffd700)
            embed.add_field(name="選項", value="1️⃣ 🔥 (裝熟)\n2️⃣ 🤡 (小丑)\n3️⃣ 💩 (噁心)\n4️⃣ 👀 (只看)", inline=False)
            msg = await channel.send(embed=embed)
            for e in ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]: await msg.add_reaction(e)
            async with aiosqlite.connect(self.db_name) as db:
                week_ago = time.time() - 604800
                cursor = await db.execute("SELECT title, artist, user_id FROM music_history WHERE timestamp > ? GROUP BY title, artist ORDER BY MAX(timestamp) DESC LIMIT 20", (week_ago,))
                rows = await cursor.fetchall()
            if rows:
                song_data = [f"{self.bot.get_user(r[2]).display_name if self.bot.get_user(r[2]) else r[2]} - {r[0]} by {r[1]}" for r in rows]
                report = await self.ask_kobe(f"這是本週歌單：\n{', '.join(song_data)}\n選出最爛的5首並羞辱。", 0, {}, 0)
                if report and "⚠️" not in report:
                    await channel.send(embed=discord.Embed(title="💩 本週最爛歌單", description=report, color=0x000000))

    @tasks.loop(hours=24)
    async def daily_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        today_str = now.strftime("%Y-%m-%d")
        if self._daily_executed == today_str: return
        if now.hour == 23 and now.minute >= 50:
            self._daily_executed = today_str
            channel = self.get_text_channel(self.bot.guilds[0]) if self.bot.guilds else None
            if not channel: return
            async with aiosqlite.connect(self.db_name) as db:
                limit = time.time() - 86400
                cursor = await db.execute("SELECT user_id, content FROM chat_logs WHERE timestamp > ? ORDER BY id DESC LIMIT 30", (limit,))
                chat_rows = await cursor.fetchall()
                cursor = await db.execute("SELECT user_id, lazy_points, msg_count FROM daily_stats ORDER BY lazy_points DESC LIMIT 3")
                rows = await cursor.fetchall()
            report = []
            for row in rows:
                m = self.bot.get_user(row[0])
                name = m.display_name if m else f"用戶{row[0]}"
                report.append(f"- {name}: 懶惰指數 {row[1]}")
            chat_summary = "無"
            if chat_rows:
                chat_summary = "\n".join([f"{self.bot.get_user(u).display_name if self.bot.get_user(u) else u}: {c}" for u, c in chat_rows])
            prompt = f"違規名單：\n{chr(10).join(report)}\n\n對話紀錄：\n{chat_summary}\n\n請寫一篇曼巴毒舌日報。"
            news = await self.ask_kobe(prompt, 0, {}, 0)
            if "⚠️" not in str(news):
                embed = discord.Embed(title="📰 曼巴日報", description=news, color=0xe74c3c)
                await channel.send(embed=embed)
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("DELETE FROM daily_stats")
                await db.commit()

    @tasks.loop(minutes=1)
    async def morning_execution(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        today_str = now.strftime("%Y-%m-%d")
        if self._morning_executed == today_str: return
        if now.hour == 8 and now.minute == 0:
            self._morning_executed = today_str
            if not self.bot.guilds: return
            guild = self.bot.guilds[0]
            channel = self.get_text_channel(guild)
            if not channel: return
            offline_members = [m for m in guild.members if not m.bot and m.status == discord.Status.offline]
            if not offline_members: return
            names = [m.display_name for m in offline_members]
            mentions = [m.mention for m in offline_members]
            prompt = f"現在是早上8點，這{len(offline_members)}個垃圾還在睡：{', '.join(names)}\n用最毒、最羞辱的方式把他們罵醒，結尾必須帶 🐍💀"
            roast = await self.ask_kobe(prompt, user_id=None, cooldown_dict={}, cooldown_time=0)
            if not roast or "⚠️" in roast or "ERROR" in roast:
                roast = f"8點了還在睡？\n{' '.join(mentions)}\n給我滾起來訓練！🐍💀"
            embed = discord.Embed(title="⏰ 08:00 起床氣處刑名單", description=f"{' '.join(mentions)}\n\n{roast}", color=0xff0000, timestamp=now)
            embed.set_footer(text="Mamba 在凌晨4點就醒了。你呢？")
            await channel.send(embed=embed)

    # ==================== 每日一問（賽級穩定版）================
    @tasks.loop(hours=24)
    async def daily_mamba_question(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        if not (now.hour == 9 and now.minute < 5):
            return
        today = now.strftime("%Y-%m-%d")
        if self.daily_question_asked == today:
            return
        self.daily_question_asked = today

        guild = self.bot.guilds[0] if self.bot.guilds else None
        if not guild:
            return
        channel = self.get_text_channel(guild)
        if not channel or not channel.permissions_for(guild.me).send_messages:
            return

        self.pending_daily_answer = set()
        self.daily_question_channel = channel
        self.daily_question_msg_id = None

        active_members = {
            m.id for m in guild.members
            if not m.bot and (m.status != discord.Status.offline or 
            (channel.last_message and channel.last_message.author == m))
        }
        if not active_members:
            return
        self.pending_daily_answer = active_members.copy()

        embed = discord.Embed(title="【每日曼巴意志測驗】", color=0x000000)
        embed.description = (
            "**今天你要變強還是繼續當廢物？**\n\n"
            "1️⃣ 變強　　2️⃣ 當廢物\n\n"
            "⏰ **60 秒內不回覆 → 公開處刑 +10 懶惰點**"
        )
        embed.set_footer(text=f"日期：{today} | Mamba is watching")

        try:
            msg = await channel.send("@everyone", embed=embed)
            await msg.add_reaction("1️⃣")
            await msg.add_reaction("2️⃣")
            self.daily_question_msg_id = msg.id

            async def execution():
                await asyncio.sleep(68)
                if self.daily_question_msg_id != msg.id:
                    return
                if not self.pending_daily_answer:
                    return
                losers = [guild.get_member(uid) for uid in self.pending_daily_answer]
                losers = [m for m in losers if m]
                if not losers:
                    return
                if len(losers) <= 20:
                    mentions = " ".join(m.mention for m in losers)
                else:
                    mentions = f"{len(losers)}名廢物（太多不逐一@）"
                roast = await self.ask_kobe(
                    f"這{len(losers)}個人60秒內沒回答每日意志測驗，極兇極毒罵醒他們，結尾一定要有🐍💀",
                    None, {}, 0
                )
                final_roast = roast or "廢物就是廢物，永遠上不了場。🐍💀"
                await channel.send(f"【意志力處刑名單】 {mentions}\n{final_roast}")
                for m in losers:
                    await self.update_daily_stats(m.id, "lazy_points", 10)
                self.pending_daily_answer.clear()
                self.daily_question_msg_id = None

            self.bot.loop.create_task(execution())

        except Exception as e:
            logger.error(f"每日一問發送失敗: {e}")
            self.daily_question_msg_id = None

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        if str(reaction.emoji) not in ["1️⃣", "2️⃣"]:
            return
        if not self.daily_question_msg_id:
            return
        if reaction.message.id != self.daily_question_msg_id:
            return
        if reaction.message.channel != self.daily_question_channel:
            return

        was_pending = user.id in self.pending_daily_answer
        self.pending_daily_answer.discard(user.id)
        if not was_pending:
            return

        if str(reaction.emoji) == "2️⃣":
            await self.update_daily_stats(user.id, "lazy_points", 5)
            try:
                await reaction.message.channel.send(
                    f"{user.mention} 公開承認自己是廢物 +5 懶惰點 🤡",
                    delete_after=10
                )
            except:
                pass

    # ==================== 情緒雷達 ====================
    @tasks.loop(minutes=15)
    async def mood_radar(self):
        guild = self.bot.guilds[0]
        channel = self.get_text_channel(guild)
        if not channel: return

        async with aiosqlite.connect(self.db_name) as db:
            limit = time.time() - 3600
            cursor = await db.execute("SELECT content FROM chat_logs WHERE timestamp > ? ORDER BY id DESC LIMIT 25", (limit,))
            rows = await cursor.fetchall()

        if len(rows) < 8: return
        text = " | ".join(r[0] for r in rows)
        mood = await self.ask_kobe(f"用一個詞總結這25句話的整體情緒：開心/低落/嗨/憤怒/冷/正常\n內容：{text}", None, {}, 0)
        if not mood: return

        if any(w in mood for w in ["低落", "難過", "沮喪", "累"]):
            await channel.send("https://youtu.be/V2v5ZsoR1Mk")
            await channel.send("「You don't get better sitting on the bench.」🐍")
        elif any(w in mood for w in ["嗨", "瘋", "笑死", "哈哈"]):
            await channel.send("『你們這叫興奮？我叫這幼稚。去訓練。』💀")

    # ==================== 深夜日報 + 長期記憶 ====================
    @tasks.loop(hours=24)
    async def daily_summary_and_memory(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        if now.hour == 0 and now.minute < 10:
            today = now.strftime("%Y-%m-%d")
            if self.last_daily_summary == today: return
            self.last_daily_summary = today

            channel = self.get_text_channel(self.bot.guilds[0])
            if not channel or not self.daily_word_count: return

            all_text = " ".join(self.daily_word_count.values())
            top5 = Counter(all_text.split()).most_common(5)
            words = "、".join(f"{w}({c}次)" for w,c in top5)

            embed = discord.Embed(title="曼巴深夜戰報", color=0x000000)
            embed.description = f"今日最常出現的詞：{words}\n\nMamba never sleeps. 你呢？🐍"
            await channel.send(embed=embed)

            self.daily_word_count.clear()

    # ==================== 黑歷史指令 ====================
    @commands.command(aliases=["黑歷史", "恥辱", "bh"])
    async def black_history(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT content FROM chat_logs WHERE user_id = ? AND content LIKE '[黑歷史]%' ORDER BY RANDOM() LIMIT 1", (target.id,))
            row = await cursor.fetchone()
            worst_sentence = row[0][5:] if row else "此人完美無缺（假的）"
            cursor = await db.execute("SELECT SUM(seconds) FROM playtime WHERE user_id = ?", (target.id,))
            total = await cursor.fetchone()
            total_hours = (total[0] or 0) // 3600

        embed = discord.Embed(title=f"🖤 黑歷史檔案：{target.display_name}", color=0x000000)
        embed.add_field(name="最廢金句", value=f"「{worst_sentence}」", inline=False)
        embed.add_field(name="總遊戲廢時", value=f"{total_hours} 小時", inline=False)
        embed.add_field(name="曼巴評語", value="Soft. 永久飲水機。🐍", inline=False)
        embed.set_thumbnail(url="https://i.imgur.com/0bX9b3A.png")
        await ctx.send(embed=embed)

    # ==================== 其他指令 ====================
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
        embed = discord.Embed(title="🏆 遊戲時長排行榜 (歷史累積)", color=0xffd700)
        desc = ""
        for i, (uid, seconds) in enumerate(sorted_stats):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"用戶({uid})"
            status = "🎮" if uid in self.active_sessions else ""
            desc += f"**{i+1}. {name}** {status}\n └ {seconds//3600}小時 {(seconds%3600)//60}分\n"
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
            if not rows: return await ctx.send("最近沒人說話。")
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
            else: await ctx.send("分析失敗。")

    @commands.command(aliases=["s", "songs", "音樂"])
    async def music_analysis(self, ctx):
        async with ctx.typing():
            async with aiosqlite.connect(self.db_name) as db:
                week_ago = time.time() - 604800
                cursor = await db.execute("SELECT title, artist FROM music_history WHERE user_id = ? AND timestamp > ? GROUP BY title, artist ORDER BY MAX(timestamp) DESC LIMIT 20", (ctx.author.id, week_ago))
                rows = await cursor.fetchall()
            if not rows: return await ctx.send(f"{ctx.author.mention} 這週沒有聽歌紀錄。")
            song_list = "\n".join([f"- {r[0]} by {r[1]}" for r in rows])
            prompt = f"這是用戶 {ctx.author.display_name} 這週聽的歌單：\n{song_list}\n請分析他的心理狀態。"
            analysis = await self.ask_kobe(prompt, ctx.author.id, {}, 0)
            if analysis and "⚠️" not in str(analysis):
                embed = discord.Embed(title=f"🎵 音樂心理分析：{ctx.author.display_name}", description=analysis, color=0x1db954)
                await ctx.send(embed=embed)
            else: await ctx.send("分析失敗。")

    @commands.command()
    async def honor(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT points FROM honor WHERE user_id = ?", (target.id,))
            row = await cursor.fetchone()
            points = row[0] if row else 0
        title = "🤡 飲水機守護神"
        if points > 500: title = "🐍 黑曼巴 (GOAT)"
        elif points > 300: title = "⭐ 全明星"
        elif points > 100: title = "🏀 先發球員"
        elif points > 0: title = "🪑 板凳暴徒"
        embed = discord.Embed(title=f"📜 {target.display_name} 的榮譽檔案", color=0xf1c40f)
        embed.add_field(name="稱號", value=title, inline=False)
        embed.add_field(name="榮譽點數", value=f"{points} 分", inline=True)
        await ctx.send(embed=embed)

    @commands.command()
    async def goal(self, ctx, *, content: str):
        self.user_goals[ctx.author.id] = content
        await ctx.send(f"📌 {ctx.author.mention} 立下誓言：**{content}**。")

    @commands.command(aliases=['d'])
    async def done(self, ctx):
        if ctx.author.id not in self.user_goals: return await ctx.send("❓ 沒目標。")
        content = self.user_goals.pop(ctx.author.id)
        await self.add_honor(ctx.author.id, 20)
        comment = await self.ask_kobe(f"用戶完成了：{content}。肯定他。", ctx.author.id, {}, 0)
        await ctx.send(f"✅ **目標達成！** (+20)\n{comment}")

    @commands.command(aliases=['b'])
    async def blame(self, ctx, target: discord.Member):
        if target == ctx.author: return await ctx.send("別自虐。")
        await self.vote_honor(ctx, target, -10, "👎 譴責")

    @commands.command(aliases=['res'])
    async def respect(self, ctx, target: discord.Member):
        if target == ctx.author: return await ctx.send("別自戀。")
        await self.vote_honor(ctx, target, 10, "🫡 致敬")

    async def vote_honor(self, ctx, target, amount, action):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT last_vote_date FROM honor WHERE user_id = ?", (ctx.author.id,))
            row = await cursor.fetchone()
            if row and row[0] == today: return await ctx.send("⏳ 今天投過了。")
            await db.execute("INSERT OR REPLACE INTO honor (user_id, points, last_vote_date) VALUES (?, (SELECT points FROM honor WHERE user_id=?), ?)", (ctx.author.id, ctx.author.id, today))
            await self.add_honor(target.id, amount)
            await db.commit()
        await ctx.send(f"{ctx.author.mention} {action} 了 {target.mention}！")

    @daily_mamba_question.before_loop
    @mood_radar.before_loop
    @daily_summary_and_memory.before_loop
    @game_check.before_loop
    @daily_tasks.before_loop
    @weekly_tasks.before_loop
    @ghost_check.before_loop
    @morning_execution.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

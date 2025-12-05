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
        
        # AI 狀態檢查
        api_key = os.getenv("GEMINI_API_KEY")
        self.has_ai = True if api_key else False

        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.toxic_words = ["幹", "靠", "爛", "輸"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍", "Soft. 🥚"]

        # 系統人設 (自動回應版)
        self.sys_prompt_template = (
            "你是 Kobe Bryant。個性：真實、不恭維、專業、現實、專注於問題。\n"
            "1. **主動對話**：你正在看著這些球員(用戶)聊天。如果他們在講廢話，插嘴罵醒他們；如果他們在討論戰術/技術，給予肯定。\n"
            "2. **回答問題**：針對用戶問題給予專業建議。**絕對不要硬扯籃球比喻**，除非真的很貼切。\n"
            "3. **音樂/遊戲審判**：嚴格審判品味。\n"
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
        self.voice_check.start()
        self.ghost_check.start()
        await self.bot.wait_until_ready()

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.game_check.cancel()
        self.voice_check.cancel()
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
                if len(self.short_term_memory[user_id]) > 20:
                    self.short_term_memory[user_id] = self.short_term_memory[user_id][:2] + self.short_term_memory[user_id][-18:]

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

    # ==========================================
    # 🎯 狀態監控
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        channel = self.get_text_channel(after.guild)
        
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        # 1. 遊戲偵測 (玩遊戲 -> 懶惰指數 +5)
        if new_game and not old_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            prompt = f"用戶開始玩 {new_game}。" + ("痛罵他玩2K是垃圾" if "2k" in new_game.lower() else "罵他不去訓練")
            roast = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            if channel: 
                await channel.send(f"{after.mention} {roast or f'玩 {new_game}？去訓練！'}")
                await self.update_daily_stats(user_id, "lazy_points", 5) # 增加懶惰指數

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

            if random.random() < 0.2: 
                prompt = f"用戶正在聽 Spotify: {new_spotify.title} - {new_spotify.artist}。請用心理學分析為什麼聽這首歌。"
                roast = await self.ask_kobe(prompt, user_id, {}, 0) 
                if channel and roast and "⚠️" not in str(roast) and roast != "COOLDOWN":
                    await channel.send(f"🎵 **DJ Mamba 點評** {after.mention}\n{roast}")

    # ==========================================
    # 💬 聊天監控 (自動回應 + 訊息計數)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.content.startswith('!'): return 

        if message.id in self.processed_msg_ids: return
        self.processed_msg_ids.add(message.id)
        if len(self.processed_msg_ids) > 1000: self.processed_msg_ids.clear()

        user_id = message.author.id
        content = message.content.strip()
        
        # 🔥 1. 紀錄訊息數 (Msg Count) & 內容
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO chat_logs (user_id, content, timestamp) VALUES (?, ?, ?)", (user_id, content, time.time()))
            # 更新 msg_count + 1
            await self.update_daily_stats(user_id, "msg_count", 1)
            if random.random() < 0.05: # 定期清理 log
                limit_time = time.time() - 86400
                await db.execute("DELETE FROM chat_logs WHERE timestamp < ?", (limit_time,))
            await db.commit()

        # Ghosting Check
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

        # 🔥 2. 自動回應 (Auto Reply - 無需指令)
        # 如果沒有 Tag，也有 5% 機率觸發 Kobe 插話
        should_auto_reply = random.random() < 0.05 and len(content) > 5

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
                if roast and "⚠️" not in str(roast) and roast != "COOLDOWN": 
                    await message.reply(roast)
                    await self.update_daily_stats(user_id, "lazy_points", 2) # 負能量 +2 懶惰
            return
        
        # 🔥 智慧插話
        elif should_auto_reply:
            async with message.channel.typing():
                 reply = await self.ask_kobe(f"用戶說：'{content}'。請根據內容隨機應變，如果是廢話就罵，如果是好話就誇。", user_id, self.ai_chat_cooldowns, 60, use_memory=True)
                 if reply and "⚠️" not in str(reply) and reply != "COOLDOWN":
                     await message.reply(reply)
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
            # 安全地更新欄位 (避免 SQL Injection, 雖此處為內部呼叫)
            if column in ["msg_count", "lazy_points"]:
                await db.execute(f"UPDATE daily_stats SET {column} = {column} + ? WHERE user_id = ?", (value, user_id))
            await db.commit()

    async def add_honor(self, user_id, amount):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (user_id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    def get_text_channel(self, guild):
        channel = guild.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            return discord.utils.find(lambda x: any(t in x.name.lower() for t in ["chat", "general", "聊天", "公頻"]) and x.permissions_for(guild.me).send_messages, guild.text_channels) or guild.text_channels[0]
        return channel

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

    @tasks.loop(seconds=60)
    async def voice_check(self):
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if member.bot: continue
                    if member.voice.self_mute:
                        if random.random() < 0.2:
                            channel = self.get_text_channel(guild)
                            if channel:
                                msg = await self.ask_kobe(f"{member.display_name} 在語音靜音。罵他。", user_id=member.id, cooldown_dict=self.status_cooldowns, cooldown_time=600)
                                if msg and "⚠️" not in str(msg): await channel.send(f"🔇 **靜音糾察** {member.mention}\n{msg}")

    # ==========================================
    # 🔥 每日 00:00 結算任務
    # ==========================================
    @tasks.loop(minutes=1)
    async def daily_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        
        # 檢查是否為 00:00 (台灣時間)
        if now.hour == 0 and now.minute == 0:
            channel = self.get_text_channel(self.bot.guilds[0]) if self.bot.guilds else None
            if not channel: return
            
            async with aiosqlite.connect(self.db_name) as db:
                # 1. 撈取廢物榜 (懶惰指數 Top 3)
                cursor = await db.execute("SELECT user_id, lazy_points, msg_count FROM daily_stats ORDER BY lazy_points DESC LIMIT 3")
                lazy_rows = await cursor.fetchall()
                
                # 2. 撈取話癆榜 (訊息數 Top 3)
                cursor = await db.execute("SELECT user_id, msg_count FROM daily_stats ORDER BY msg_count DESC LIMIT 3")
                chatty_rows = await cursor.fetchall()

                # 3. 撈取聊天摘要 (最近 24h)
                limit_time = time.time() - 86400 
                cursor = await db.execute("SELECT user_id, content FROM chat_logs WHERE timestamp > ? ORDER BY id DESC LIMIT 30", (limit_time,))
                chat_rows = await cursor.fetchall()

            # 生成報告文字
            report_text = ""
            if lazy_rows:
                report_text += "**🏆 今日最廢三人組 (懶惰指數)：**\n"
                for i, row in enumerate(lazy_rows):
                    m = self.bot.get_user(row[0])
                    name = m.display_name if m else f"User{row[0]}"
                    report_text += f"{i+1}. {name} - 懶惰值 {row[1]} (發言 {row[2]})\n"
            
            if chatty_rows:
                report_text += "\n**🗣️ 今日曼巴話癆 (訊息數)：**\n"
                for i, row in enumerate(chatty_rows):
                    m = self.bot.get_user(row[0])
                    name = m.display_name if m else f"User{row[0]}"
                    report_text += f"{i+1}. {name} - {row[1]} 則\n"

            chat_summary = "無"
            if chat_rows: chat_summary = "\n".join([f"{self.bot.get_user(u).display_name if self.bot.get_user(u) else u}: {c}" for u, c in chat_rows])

            # AI 總結
            prompt = f"這是今日數據：\n{report_text}\n\n對話內容：\n{chat_summary}\n\n請以「曼巴日報總編輯」身份，寫一篇毒舌日報，狠批最廢的人，並點評話最多的人。"
            news = await self.ask_kobe(prompt, 0, {}, 0)
            
            if "⚠️" not in str(news):
                embed = discord.Embed(title="📰 曼巴日報 (00:00 結算)", description=news, color=0xe74c3c)
                if report_text: embed.add_field(name="📊 數據榜單", value=report_text, inline=False)
                await channel.send(embed=embed)

            # 🔥 清空今日數據
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("DELETE FROM daily_stats")
                await db.execute("DELETE FROM playtime") 
                await db.commit()
    
    # ... (指令部分保持不變) ...
    @commands.command(aliases=['r'])
    async def rank(self, ctx):
        # ... (同上)
        pass 
    @commands.command(aliases=["st", "狀況"])
    async def status(self, ctx):
        # ... (同上)
        pass
    @commands.command(aliases=["summary", "recap", "總結"])
    async def chat_summary(self, ctx):
        # ... (同上)
        pass
    @commands.command(aliases=["s", "songs", "音樂"])
    async def music_analysis(self, ctx):
        # ... (同上)
        pass

    @game_check.before_loop
    @daily_tasks.before_loop
    @voice_check.before_loop
    @ghost_check.before_loop
    async def before_loops(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

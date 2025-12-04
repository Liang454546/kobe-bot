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
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.emoji_cooldowns = {} # 表情符號冷卻
        self.image_cooldowns = {}
        
        # --- AI 設定 (Gemini 2.0 Flash) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (翻舊帳+表情審判版)")
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
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格。教練模式：專業指導但嚴厲。痛恨懶惰與 2K。繁體中文(台灣)。"
            contents = [sys_prompt, f"情境：{prompt}"]
            if image: contents.append(image)
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except: return None

    # ==========================================
    # 🕵️ 資料庫搜查 (翻舊帳用)
    # ==========================================
    async def get_past_playtime(self, user_id, game_name):
        """查詢這個人歷史上玩了多久這款遊戲"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT seconds FROM playtime WHERE user_id = ? AND game_name = ?", (user_id, game_name))
            row = await cursor.fetchone()
            return row[0] if row else 0

    # ==========================================
    # 🤡 AI 表情審判
    # ==========================================
    async def judge_with_emoji(self, message):
        """讓 AI 決定要對這則訊息按什麼表情"""
        try:
            # 簡單分類，省 Token
            prompt = (
                f"分析這句話：'{message.content}'。\n"
                "如果是軟弱/藉口/偷懶，回傳 'WEAK'。\n"
                "如果是努力/熱血/訓練，回傳 'STRONG'。\n"
                "如果是廢話或無關，回傳 'NONE'。\n"
                "只回傳單字，不要其他文字。"
            )
            response = await asyncio.to_thread(self.model.generate_content, contents=prompt)
            result = response.text.strip().upper()

            if "WEAK" in result:
                emoji = random.choice(["🤡", "💩", "📉", "👎", "🛌"])
                await message.add_reaction(emoji)
            elif "STRONG" in result:
                emoji = random.choice(["🔥", "🏀", "🐍", "💪", "📈"])
                await message.add_reaction(emoji)
        except:
            pass

    # ==========================================
    # 🎯 遊戲狀態監控 (翻舊帳版)
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

        # A. 遊戲開始 (AI 翻舊帳)
        if new_game and not old_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            
            # 🔥 查詢歷史時數
            total_seconds = await self.get_past_playtime(user_id, new_game)
            total_hours = total_seconds // 3600
            
            # 構建超兇 Prompt
            prompt = f"用戶開始玩 {new_game} 了。"
            if total_hours > 10:
                prompt += f"資料庫顯示他已經在我們伺服器玩這款遊戲累積 **{total_hours} 小時**了！"
                prompt += "用這個數據狠狠羞辱他，說這些時間拿去訓練早就變強了。"
            elif "2k" in new_game.lower():
                prompt += "痛罵他玩 2K 是電子垃圾。"
            else:
                prompt += "罵他不去訓練。"

            roast = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            
            if not roast or roast == "COOLDOWN": 
                roast = f"又在玩 **{new_game}**？你已經浪費 {total_hours} 小時在這上面了！😡"
            
            if channel: await channel.send(f"{after.mention} {roast}")

        # B. 遊戲結束
        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                
                if duration > 600 and channel:
                    interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘。質問他。", user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN": 
                        await channel.send(f"🎤 **賽後毒舌採訪** {after.mention}\n{interview}")

    # ==========================================
    # 💬 聊天監控 (表情審判)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.content.startswith('!'): return 

        user_id = message.author.id
        content = message.content
        is_mentioned = self.bot.user in message.mentions or message.content.strip().endswith("?")
        
        # 1. AI 對話
        if is_mentioned:
            async with message.channel.typing():
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 5)
                await message.reply(reply or random.choice(self.kobe_quotes))
            return

        # 2. 🔥 AI 表情審判 (無聲的壓力)
        # 為了省資源，設定 20% 機率觸發，或者針對長句子
        if len(content) > 5 and random.random() < 0.5:
            # 檢查冷卻
            now = time.time()
            if now - self.emoji_cooldowns.get(user_id, 0) > 30:
                self.emoji_cooldowns[user_id] = now
                asyncio.create_task(self.judge_with_emoji(message))

        # 3. 圖片審判
        if message.attachments:
             if any(message.attachments[0].content_type.startswith(t) for t in ["image/"]):
                async with message.channel.typing():
                    reply = await self.analyze_image(message.attachments[0].url, user_id)
                    await message.reply(reply)
                return

        await self.bot.process_commands(message)

    # ==========================================
    # 其他功能 (維持原樣)
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
            reply = await self.ask_kobe("分析這張圖。毒舌點評。", user_id, {}, 0, image=image)
            return reply
        except: return random.choice(self.kobe_quotes)

    # ... (資料庫存檔、更新 daily stats、add honor 等 helper functions 維持原樣) ...
    # 請務必保留原有的 save_to_db, update_daily_stats, add_honor, get_text_channel, rank, status 指令
    
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

    # ... (Tasks 保持不變) ...
    @commands.command(aliases=['r'])
    async def rank(self, ctx):
        # ... (同上版 Rank 代碼) ...
        pass
    
    @commands.command(aliases=["st", "狀況"])
    async def status(self, ctx):
        # ... (同上版 Status 代碼) ...
        pass

    @tasks.loop(minutes=1)
    async def game_check(self):
        # ... (同上版 game_check 邏輯) ...
        pass
        
    async def send_warning(self, user_id, game, time_str, penalty):
        # ... (同上版 send_warning) ...
        pass

    @tasks.loop(hours=24)
    async def daily_tasks(self): pass
    @tasks.loop(seconds=30)
    async def voice_check(self): pass
    @game_check.before_loop
    @daily_tasks.before_loop
    @voice_check.before_loop
    async def before_loops(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

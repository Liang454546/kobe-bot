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
        
        # 狀態與冷卻
        self.active_sessions = {}
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        
        # 🔥 新增：對話記憶庫 {user_id: [{"role": "user", "parts": [...]}, ...]}
        self.chat_histories = {} 
        self.last_chat_time = {} # 用來判斷記憶是否過期
        
        # --- AI 設定 ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (記憶教練模式)")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        # 關鍵字庫
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
    # 🧠 AI 核心：含記憶功能的問答
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None, use_memory=False):
        if not self.has_ai: return None

        now = time.time()
        
        # 1. 冷卻檢查
        if user_id and cooldown_dict:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
            cooldown_dict[user_id] = now

        # 2. 記憶管理 (僅針對對話模式)
        history = []
        if use_memory and user_id:
            # 如果超過 10 分鐘沒講話，清空舊記憶 (避免錯亂)
            if now - self.last_chat_time.get(user_id, 0) > 600:
                self.chat_histories[user_id] = []
            
            # 取得歷史紀錄
            history = self.chat_histories.get(user_id, [])
            self.last_chat_time[user_id] = now

        try:
            # 3. 系統人設 (System Prompt)
            sys_prompt = (
                "你是 Kobe Bryant。個性：毒舌、嚴格、有哲理、痛恨懶惰。\n"
                "規則：\n"
                "1. **問問題**：專業回答，但語氣嚴厲。\n"
                "2. **閒聊**：根據上下文回應，如果對方軟弱就罵醒他。\n"
                "3. **提到 2K**：暴怒。\n"
                "4. 繁體中文(台灣)，50字內，多用 emoji (🏀🐍)。"
            )

            # 4. 組合最終 Prompt
            # 如果有圖片，不使用歷史紀錄 (Gemini 限制)，直接單次詢問
            if image:
                contents = [sys_prompt, prompt, image]
            else:
                # 這裡我們手動組合歷史紀錄送給 AI
                # 格式: [System, User, Model, User, Model, ... Current User]
                contents = [{"role": "user", "parts": [sys_prompt]}] 
                
                # 填入歷史
                for h in history:
                    contents.append(h)
                
                # 填入當前問題
                contents.append({"role": "user", "parts": [prompt]})

            # 5. 發送請求
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            reply_text = response.text

            # 6. 更新記憶
            if use_memory and user_id and not image:
                # 存入這次的對話
                self.chat_histories.setdefault(user_id, []).append({"role": "user", "parts": [prompt]})
                self.chat_histories[user_id].append({"role": "model", "parts": [reply_text]})
                
                # 限制記憶長度 (只記最近 6 輪對話，避免 Token 爆炸)
                if len(self.chat_histories[user_id]) > 12:
                    self.chat_histories[user_id] = self.chat_histories[user_id][-12:]

            return reply_text

        except Exception as e:
            logger.error(f"AI 呼叫錯誤: {e}") 
            return "ERROR"

    # ==========================================
    # 💬 聊天監控 (啟用記憶)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.content.startswith('!'): return 

        user_id = message.author.id
        content = message.content
        
        # 1. AI 對話 (被標記 或 ? 結尾)
        is_mentioned = self.bot.user in message.mentions or (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user) or message.content.strip().endswith("?")
        
        if is_mentioned:
            async with message.channel.typing():
                # 🔥 關鍵：use_memory=True
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 3, use_memory=True)

                if reply == "COOLDOWN":
                    await message.add_reaction("🕒") # 用表情代替文字，減少干擾
                elif reply == "ERROR":
                    await message.reply("⚠️ 腦袋當機了 (AI Error)。")
                elif reply:
                    await message.reply(reply)
                else:
                    await message.reply(random.choice(self.kobe_quotes))
            return

        # 2. 圖片審判 (不記記憶，單次觸發)
        if message.attachments:
            if any(message.attachments[0].content_type.startswith(t) for t in ["image/"]):
                async with message.channel.typing():
                    reply = await self.analyze_image(message.attachments[0].url, user_id)
                    await message.reply(reply)
                return

        # 3. 關鍵字 (不記記憶)
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.update_daily_stats(user_id, "lazy_points", 2)
        elif any(w in content for w in self.strong_words):
            await message.channel.send(f"{message.author.mention} 這才是曼巴精神！🏀")
            await self.add_honor(user_id, 2)
            
        await self.bot.process_commands(message)

    # ==========================================
    # 其他功能 (維持原樣)
    # ==========================================
    # ... (請保留原本的 on_presence_update, analyze_image, save_to_db, tasks 等所有程式碼) ...
    # 為了節省篇幅，以下函式請直接沿用上一版，功能完全沒變，只需確保 ask_kobe 已更新
    
    async def analyze_image(self, image_url, user_id):
        # 這裡呼叫 ask_kobe 時，use_memory=False (預設)
        # ... (同上一版邏輯) ...
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200: return "圖片讀取失敗。"
                    data = await resp.read()
            image = Image.open(io.BytesIO(data))
            reply = await self.ask_kobe("分析這張圖。毒舌點評。", user_id, self.image_cooldowns, 60, image=image)
            return reply or "我看不到曼巴精神。🐍"
        except: return random.choice(self.kobe_quotes)

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        # ... (同上一版邏輯，記得把裡面的 ask_kobe 呼叫加上 await) ...
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
            # 這裡不使用記憶，因為是單向罵人
            roast = await self.ask_kobe(f"這軟蛋開始玩 {new_game} 了。罵他。", user_id, self.ai_roast_cooldowns, 300)
            if channel: await channel.send(f"{after.mention} {roast or '玩遊戲？不用唸書嗎？😡'}")

        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                if duration > 600 and channel:
                    # 這裡也不用記憶
                    interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘。質問他。", user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN": await channel.send(f"🎤 **賽後採訪** {after.mention}\n{interview}")

    # ... (Helper Functions & Tasks 同上一版) ...
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
            if not await cursor.fetchone():
                await db.execute("INSERT INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
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
    @tasks.loop(hours=24)
    async def daily_tasks(self): pass
    @tasks.loop(minutes=1)
    async def game_check(self):
        # ... (同上版警告邏輯) ...
        pass
    @tasks.loop(seconds=30)
    async def voice_check(self): pass
    @game_check.before_loop
    @daily_tasks.before_loop
    @voice_check.before_loop
    async def before_loops(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

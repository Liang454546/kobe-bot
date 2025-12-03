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

        # 冷卻相關
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}

        # 關鍵字庫
        self.weak_words = ["累", "想睡", "放棄", "休息", "好累", "睡了"]
        self.strong_words = ["健身", "訓練", "加班", "努力", "衝", "練"]
        self.procrastination_words = ["等下", "明天", "之後", "先休息", "再看", "晚點", "等會"]
        self.liar_keywords = ["讀書", "寫作業", "健身", "忙", "加班", "在努力"]
        self.kobe_quotes = [
            "Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍",
            "Soft. 🥚", "你見過洛杉磯凌晨四點嗎？", "輸給誰都不可以輸給自己。"
        ]

        # === 關鍵：2025 年 Gemini 正確初始化方式 ===
        self.model = None
        self.has_ai = False
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    generation_config={
                        "temperature": 0.9,
                        "max_output_tokens": 80,
                        "top_p": 0.95,
                    },
                    safety_settings=[
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
                    ]
                )
                self.has_ai = True
                logger.info("Gemini 1.5 Flash 啟動成功 (支援 Vision + Async)")
            except Exception as e:
                logger.error(f"Gemini 初始化失敗: {e}")
                self.has_ai = False
        else:
            logger.warning("未設定 GEMINI_API_KEY，AI 功能關閉")
            self.has_ai = False

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
        self.random_mood.start()
        self.voice_check.start()
        logger.info("Game Cog 加載完成")

    async def cog_unload(self):
        for task in [self.daily_tasks, self.game_check, self.random_mood, self.voice_check]:
            if task.is_running():
                task.cancel()

    # =============================================
    # 核心 AI 函數（完全 async + 防掛 + retry）
    # =============================================
    async def ask_kobe(self, prompt: str, user_id: int = None, cooldown_dict: dict = None, cooldown_time: int = 30, image = None) -> str:
        if not self.has_ai:
            return random.choice(self.kobe_quotes)

        # 冷卻檢查
        if user_id and cooldown_dict:
            now = time.time()
            async with self.cooldown_locks:
                last = cooldown_dict.get(user_id, 0)
                if now - last < cooldown_time:
                    return None
                cooldown_dict[user_id] = now

        full_prompt = f"你是 Kobe Bryant，在一個 3 人小 Discord 當毒舌教練。用繁體中文（台灣腔），語氣嚴厲但勵志，30 字內，多 emoji 🏀🐍\n\n{prompt}"

        for attempt in range(3):
            try:
                if image:
                    response = await self.model.generate_content_async([full_prompt, image])
                else:
                    response = await self.model.generate_content_async(full_prompt)
                
                text = response.text.strip()
                return text if text else "Mamba never quits. 🐍"
                
            except Exception as e:
                logger.error(f"AI 第 {attempt+1} 次失敗: {e}")
                if "quota" in str(e).lower() or "429" in str(e):
                    return "冷卻中...別吵我訓練！🏀"
                if attempt < 2:
                    await asyncio.sleep(2)
                continue

        return random.choice(self.kobe_quotes)

    # =============================================
    # 圖片分析（2025 最新 Vision 寫法）
    # =============================================
    async def analyze_image(self, image_url: str, user_id: int) -> str:
        async with self.cooldown_locks:
            now = time.time()
            if now - self.image_cooldowns.get(user_id, 0) < 60:
                return "冷卻中...別一直傳垃圾圖！😤"
            self.image_cooldowns[user_id] = now

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200:
                        return "圖片壞了，軟蛋！🥚"
                    data = await resp.read()

            image = Image.open(io.BytesIO(data))
            # 直接傳 PIL 物件（最新版支援）
            reply = await self.ask_kobe(
                prompt="分析這張圖，這傢伙在幹嘛？他在偷懶嗎？毒舌批評他！",
                user_id=user_id,
                cooldown_dict=self.image_cooldowns,
                cooldown_time=60,
                image=image
            )
            return reply or "這圖太軟了！去練球！🏀"

        except asyncio.TimeoutError:
            return "圖片太慢了，跟你一樣軟！🐍"
        except Exception as e:
            logger.error(f"圖片分析錯誤: {e}")
            return random.choice(self.kobe_quotes)

    # =============================================
    # 其他功能（on_message, tasks 等）保持不變
    # =============================================
    def get_broadcast_channel(self, guild=None):
        if not guild and self.bot.guilds:
            guild = self.bot.guilds[0]
        if not guild:
            return None
        targets = ["general", "chat", "聊天", "公頻", "閒聊"]
        return next((c for c in guild.text_channels if any(t in c.name.lower() for t in targets)), None) or guild.text_channels[0]

    # 你的其他 @tasks.loop 和 on_message 事件直接沿用之前版本即可

    @tasks.loop(hours=24)
    async def daily_tasks(self):
        await self.bot.wait_until_ready()
        # 重置每日統計等邏輯...

    @tasks.loop(minutes=5)
    async def game_check(self):
        await self.bot.wait_until_ready()
        # 遊戲時長追蹤...

    @tasks.loop(minutes=30)
    async def random_mood(self):
        await self.bot.wait_until_ready()
        channel = self.get_broadcast_channel()
        if channel and random.random() < 0.3:
            await channel.send(random.choice([
                "誰在偷懶？🐍", "Mamba never quits.", "還不快去訓練？🏀",
                "我怎麼聞到軟蛋的味道？🥚"
            ]))

    @tasks.loop(seconds=30)
    async def voice_check(self):
        await self.bot.wait_until_ready()
        # 語音偵測邏輯...

async def setup(bot):
    await bot.add_cog(Game(bot))

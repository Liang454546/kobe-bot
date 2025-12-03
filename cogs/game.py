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

# 設定 log
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
        self.last_message_time = {}
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        
        # --- 1. 設定 AI (修：換新模型，v1beta 相容) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                # 修：改 gemini-1.5-flash (2025 穩定版，支援 vision，免 404)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                self.has_ai = True
                logger.info("✅ Gemini 1.5 Flash 啟動成功 (vision OK)")
                print("✅ Gemini 1.5 Flash 啟動成功")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
                print(f"❌ AI 啟動失敗: {e}")
        else:
            logger.warning("⚠️ GEMINI_API_KEY 缺失，AI 備用模式")
            self.has_ai = False
            print("⚠️ 警告：找不到 GEMINI_API_KEY")

        # 關鍵字庫（不變）
        self.weak_words = ["累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍", "Soft. 🥚"]
        self.procrastination_words = ["等下", "明天", "之後", "先休息", "再看", "晚點"]
        self.liar_keywords = ["讀書", "寫作業", "健身", "忙", "加班"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE)')
            await db.commit()
        
        # 啟動自動任務
        self.daily_tasks.start()
        self.game_check.start()
        self.random_mood.start()
        self.voice_check.start()

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.game_check.cancel()
        self.random_mood.cancel()
        self.voice_check.cancel()

    # 更新每日統計（不變）
    async def update_daily_stats(self, user_id, key, increment=1):
        async with aiosqlite.connect(self.db_name) as db:
            now = datetime.now(timezone.utc).date()
            await db.execute('''
                INSERT OR IGNORE INTO daily_stats (user_id, msg_count, lazy_points, roasted_count, last_updated)
                VALUES (?, 0, 0, 0, ?)
            ''', (user_id, now))
            await db.execute(f'UPDATE daily_stats SET {key} = {key} + ? WHERE user_id = ? AND last_updated = ?', (increment, user_id, now))
            await db.commit()

    # ==========================================
    # AI 核心：通用問答 (修：加 retry 防 404/timeout)
    # ==========================================
    async def ask_kobe(self, prompt, user_id=0, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: 
            logger.warning("AI 離線，備用 Kobe 名言")
            return random.choice(self.kobe_quotes)

        now = time.time()
        async with self.cooldown_locks:
            if cooldown_dict and user_id and now - cooldown_dict.get(user_id, 0) < cooldown_time: return None
            if cooldown_dict and user_id: cooldown_dict[user_id] = now

        for attempt in range(3):  # 新增：retry 3 次，防 timeout
            try:
                sys_prompt = "你是 Kobe Bryant，在 3 人小 Discord 聊天室當教練。語氣毒舌、嚴格但勵志。請用繁體中文(台灣)。回答簡短有力(30字內)，多用 emoji (🏀🐍)。"
                contents = [sys_prompt, prompt]
                if image: contents.append(image)
                
                response = await asyncio.to_thread(self.model.generate_content, contents=contents)
                return response.text
            except Exception as e:
                logger.error(f"AI 生成失敗 (嘗試 {attempt+1}): {e}")
                if "404" in str(e) or "not found" in str(e):
                    logger.error("模型 404？換 gemini-1.5-pro 試試，或檢查 API key。")
                    return None  # 致命，別 retry
                await asyncio.sleep(1)  # 防 rate limit
        return None  # 最終失敗

    # 圖片分析（修：加 timeout 防 hang）
    async def analyze_image(self, image_url, user_id):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:  # 新增：10s timeout
                    img_data = await resp.read()
                    image = Image.open(io.BytesIO(img_data))
                    img_part = genai.upload_file(image)
            
            prompt = "分析這張圖，判斷用戶是否在偷懶（e.g., 睡覺、玩遊戲）。毒舌回饋，用繁體中文。"
            reply = await self.ask_kobe(prompt, user_id, self.image_cooldowns, 60, img_part)
            return reply or "這圖太軟了！😤 去訓練吧。🏀"
        except asyncio.TimeoutError:
            logger.error("圖片下載 timeout")
            return random.choice(self.kobe_quotes)
        except Exception as e:
            logger.error(f"圖片分析失敗: {e}")
            return random.choice(self.kobe_quotes)

    # ... (其他函式如 on_presence_update, on_message, 任務等，不變，借之前完整版)
    # (為了節省空間，假設你 copy 之前版；若需全碼，說一聲)

    def get_broadcast_channel(self, guild=None):
        if not guild and self.bot.guilds: guild = self.bot.guilds[0]
        if not guild: return None
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target), guild.text_channels) or guild.text_channels[0]

async def setup(bot):
    await bot.add_cog(Game(bot))

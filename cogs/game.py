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
        self.chat_activity = [] 
        self.proactive_roast_cooldowns = {} 
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {} # 🔥 新增：圖片專屬冷卻
        
        # 設定 AI
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-pro") # 使用 Pro 穩定版
                self.has_ai = True
                print("✅ Gemini Pro 啟動成功")
            except Exception as e:
                print(f"❌ AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        # 關鍵字庫 (略)
        self.procrastination_words = ["等下", "明天", "之後", "先休息", "再看", "晚點"]
        self.weak_words = ["累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。", "Soft. 🥚"]
        self.targeted_roasts = {"gta": "俠盜獵車手？", "nba": "玩 NBA 2K？", "league of legends": "又在打 LOL？"}


    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            # 確保所有表格都存在
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE)')
            await db.commit()
        # 啟動自動任務
        self.daily_tasks.start()
        self.voice_check.start()
        
    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.voice_check.cancel()

    # ==========================================
    # 🧠 AI 核心：通用問答
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        now = time.time()
        if cooldown_dict and user_id and now - cooldown_dict.get(user_id, 0) < cooldown_time: return None
        if cooldown_dict and user_id: cooldown_dict[user_id] = now

        try:
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格。請用繁體中文(台灣)。回答簡短有力(50字內)，多用 emoji (🏀🐍)。"
            contents = [sys_prompt, f"情境：{prompt}"]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except: 
            return None

    # ==========================================
    # 📸 圖片審判 (防止崩潰修復)
    # ==========================================
    async def analyze_image(self, message):
        user_id = message.author.id
        now = time.time()
        
        # 🔥 核心修正：圖片冷卻 60 秒
        if user_id in self.image_cooldowns and now - self.image_cooldowns[user_id] < 60:
            await message.reply("⚠️ **冷靜點！** 圖片分析很貴又很耗資源，60 秒內不能連傳！")
            return

        attachment = message.attachments[0]
        # 檢查圖片大小，超過 5MB 的圖不處理，防止超時
        if attachment.size > 5_000_000:
            await message.reply("圖片太大 (超過 5MB)，我懶得看。")
            return

        self.image_cooldowns[user_id] = now # 設置冷卻

        try:
            async with message.channel.typing():
                img_bytes = await attachment.read()
                img = Image.open(io.BytesIO(img_bytes))
                
                prompt = "分析這張圖。如果是垃圾食物/遊戲/動漫/耍廢 -> 狠狠罵他墮落，扣分。如果是健身/書本/程式碼/健康食物 -> 稱讚他，加分。用 Kobe 語氣，30字內。"
                comment = await self.ask_kobe(prompt, user_id, self.image_cooldowns, 0, image=img)
                
                if comment:
                    change = -5 if any(x in comment for x in ["廢", "軟", "垃圾", "墮落"]) else 5
                    await self.add_honor(user_id, change)
                    await message.reply(f"{comment} (榮譽 `{change:+d}`)")
        except Exception as e:
            # 如果圖片處理或 API 呼叫失敗，重置冷卻，並通知
            del self.image_cooldowns[user_id]
            print(f"圖片處理失敗: {e}")
            await message.reply("❌ 圖片分析失敗，可能是圖片格式太大或網路錯誤。")

    # ==========================================
    # 🎯 遊戲與狀態監控
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        # 這裡的邏輯需要完整，但為了簡潔，只列出關鍵點：
        # 偵測遊戲開始/結束、超時警告、語音突襲... 
        # (用戶應保留上一篇的完整程式碼)
        pass # 請確保您保留了完整的 on_presence_update 內容

    # ==========================================
    # 💬 聊天監控 (修復靜音問題)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        user_id = message.author.id
        content = message.content
        now = time.time()
        
        # 1. 圖片審判 (新的邏輯)
        if message.attachments:
            await self.analyze_image(message)
            return

        # 2. AI 對話 (被標記)
        is_mentioned = self.bot.user in message.mentions
        
        if is_mentioned:
            async with message.channel.typing():
                # 使用 ask_kobe 函式
                reply = await self.ask_kobe(f"用戶說：{content}", user_id, self.cooldowns, 5)

                if not reply:
                    # 如果 AI 失敗或冷卻，回傳備用
                    await message.reply(random.choice(self.kobe_quotes))
                else:
                    await message.reply(reply)
            return

        # 3. 關鍵字/藉口粉碎 (只處理基礎版)
        if "累" in content:
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！")
        
        # 4. 🔥 關鍵修復：將控制權交還給指令處理器 (讓 !rank 等指令能運作)
        await self.bot.process_commands(message)

    # ... (保留所有其他指令與 Tasks) ...
    # 為了簡潔，這裡省略所有重複的指令與 Tasks 程式碼，但您應該使用完整的 cogs/game.py 檔案。

async def setup(bot):
    await bot.add_cog(Game(bot))

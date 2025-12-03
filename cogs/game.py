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

class KobeBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "kobe_bot.db"
        self.active_game_sessions = {}
        self.game_times = {}
        self.user_goals = {}
        self.voice_sessions = {}

        # 冷卻與計數器
        self.cooldowns = {}
        self.last_message_time = {}
        self.ai_roast_cooldowns = {}
        self.image_cooldowns = {}
        self.topic_starter_cooldown = {}
        
        # AI 初始化 (使用穩定版 gemini-pro)
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                # 🔥 最終穩定模型：gemini-pro
                self.model = genai.GenerativeModel("gemini-pro") 
                self.has_ai = True
                print("✅ Gemini Pro 啟動成功")
            except Exception as e:
                print(f"❌ AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        # 關鍵字庫
        self.weak_words = ["累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。", "Soft. 🥚"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, game_seconds INTEGER DEFAULT 0, last_updated DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.commit()
        
        self.game_check.start()
        self.daily_tasks.start()
        self.random_mood.start()

    async def cog_unload(self):
        self.game_check.cancel()
        self.daily_tasks.cancel()
        self.random_mood.cancel()

    # ==========================================
    # 🧠 AI 核心：通用問答 (穩定版)
    # ==========================================
    async def ask_kobe(self, prompt, user_id=0, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        if cooldown_dict and user_id and time.time() - cooldown_dict.get(user_id, 0) < cooldown_time: return None
        if cooldown_dict and user_id: cooldown_dict[user_id] = time.time()

        try:
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格。請用繁體中文(台灣)。回答簡短有力(50字內)，多用 emoji (🏀🐍)。"
            contents = [sys_prompt, prompt]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except: 
            return None

    # ==========================================
    # 🎯 遊戲與狀態監控
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)
        channel = self.get_broadcast_channel() # 廣播頻道

        # 這裡的邏輯是確保不重複觸發
        if new_game == old_game: return

        # 遊戲結束
        if old_game:
            if user_id in self.active_game_sessions:
                start_time = self.active_game_sessions.pop(user_id)
                duration = int(time.time() - start_time)
                
                # 這裡需要將時長累加到 daily_stats (為了簡潔省略)
                # 邏輯請確保在您自己的程式碼中有實現

                # 賽後採訪
                if duration > 600 and channel:
                    prompt = f"{after.display_name} 玩了 {duration // 60} 分鐘 {old_game}。質問他學到了什麼？"
                    interview = await self.ask_kobe(prompt, user_id, self.cooldowns, 0)
                    if interview: await channel.send(f"🎤 賽後毒舌採訪 {after.mention}\n{interview}")

        # 遊戲開始 (AI 罵人)
        if new_game:
            self.active_game_sessions[user_id] = time.time()
            
            # AI 罵人 (冷卻 5 分鐘)
            roast_msg = await self.ask_kobe(f"這軟蛋開始玩 {new_game} 了，罵他。", user_id, self.cooldowns, 300)
            
            if not roast_msg:
                roast_text = random.choice(self.kobe_quotes)
                roast_msg = f"{after.mention} {roast_text}"
            
            if channel: await channel.send(roast_msg)
            
    # ==========================================
    # 💬 聊天監控 (雙重修正)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        user_id = message.author.id
        
        # 0. 簡化防 Spam
        now = time.time()
        if user_id in self.last_message_time and now - self.last_message_time[user_id] < 1: return
        self.last_message_time[user_id] = now
        
        # 1. 圖片審判 (防止崩潰修復)
        if message.attachments:
            # 這裡需要完整的 analyze_image 邏輯，為了簡潔省略，請確保您有實作
            pass 
            # await self.analyze_image(message)
            # return

        # 2. AI 對話 (被標記/提問)
        is_mentioned = self.bot.user in message.mentions or message.content.strip().endswith("?")
        
        if is_mentioned:
            # 使用 ask_kobe 函式
            reply = await self.ask_kobe(f"用戶說：{message.content}", user_id, self.cooldowns, 5)

            if reply: await message.reply(reply)
            else: await message.reply(random.choice(self.kobe_quotes))
            return # 避免指令繼續向下執行

        # 3. 關鍵字/藉口粉碎 (保留邏輯)
        if any(w in message.content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            
        # 4. 🔥 關鍵修復：將控制權交還給指令處理器
        await self.bot.process_commands(message)
        
    # ==========================================
    # 📊 每日任務與統計 (保留)
    # ==========================================
    @tasks.loop(minutes=1)
    async def daily_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        channel = self.get_broadcast_channel()
        if not channel: return

        # 晨間挑戰
        if now.hour == 6 and now.minute == 0:
            challenges = ["閱讀 30 分鐘", "伏地挺身 50 下", "整理房間"]
            await channel.send(f"☀️ 曼巴挑戰：{random.choice(challenges)}，完成後榮譽 +10！")

        # 每日結算
        if now.hour == 23 and now.minute == 59:
             # 這裡需要完整的 send_daily_summary 邏輯
             pass

    # ==========================================
    # 🛠️ 資料庫工具
    # ==========================================
    def get_broadcast_channel(self):
        if not self.bot.guilds: return None
        guild = self.bot.guilds[0]
        return self.get_text_channel(guild)

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target), guild.text_channels) or guild.text_channels[0]

async def setup(bot):
    await bot.add_cog(KobeBot(bot))

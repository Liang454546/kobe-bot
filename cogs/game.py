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
        self.last_message_time = {}
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        
        # --- 1. 設定 AI (Gemini Pro - 穩定版) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-pro")
                self.has_ai = True
                print("✅ Gemini Pro 啟動成功")
            except Exception as e:
                print(f"❌ AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            print("⚠️ 警告：找不到 GEMINI_API_KEY")
            self.has_ai = False

        # 關鍵字庫
        self.weak_words = ["累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。", "Soft. 🥚"]
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


    # ==========================================
    # 🧠 AI 核心：通用問答 (穩定版)
    # ==========================================
    async def ask_kobe(self, prompt, user_id=0, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        now = time.time()
        # 檢查冷卻
        if cooldown_dict and user_id and time.time() - cooldown_dict.get(user_id, 0) < cooldown_time: return None
        if cooldown_dict and user_id: cooldown_dict[user_id] = time.time()

        try:
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格。請用繁體中文(台灣)。回答簡短有力(30字內)，多用 emoji (🏀🐍)。"
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
        channel = self.get_broadcast_channel()

        # 這裡的邏輯是確保不重複觸發
        if new_game == old_game: return

        # 遊戲結束 (存檔 + 採訪)
        if old_game:
            if user_id in self.active_sessions:
                start_time = self.active_sessions.pop(user_id)
                duration = int(time.time() - start_time)
                
                # 這裡需要將時長累加到 daily_stats
                # (略過資料庫儲存細節，請確保有實作)

                # 賽後採訪
                if duration > 600 and channel:
                    prompt = f"{after.display_name} 玩了 {duration // 60} 分鐘 {old_game}。質問他學到了什麼？"
                    interview = await self.ask_kobe(prompt, user_id, self.cooldowns, 0)
                    if interview: await channel.send(f"🎤 賽後毒舌採訪 {after.mention}\n{interview}")

        # 遊戲開始 (AI 罵人)
        if new_game:
            self.active_sessions[user_id] = time.time()
            
            # AI 罵人 (冷卻 5 分鐘)
            roast_msg = await self.ask_kobe(f"這軟蛋開始玩 {new_game} 了，罵他。", user_id, self.cooldowns, 300)
            
            # 如果 AI 失敗，用備用
            if not roast_msg:
                roast_msg = random.choice(self.kobe_quotes)
            
            if channel: await channel.send(roast_msg)
            
            # 語音查哨 (無聲)
            if after.voice and after.voice.channel:
                try:
                    # 這裡需要將 Bot 連線到語音頻道
                    pass # 假設 connect 邏輯已在 voice.py 處理
                except: pass

    # ==========================================
    # 💬 聊天監控 (修復靜音 + 指令處理)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        user_id = message.author.id
        content = message.content
        
        # 1. AI 對話 (被標記或提問)
        is_mentioned = self.bot.user in message.mentions or message.content.strip().endswith("?")
        
        if is_mentioned:
            async with message.channel.typing():
                # 使用 ask_kobe 函式
                reply = await self.ask_kobe(f"用戶問：{content}", user_id, self.cooldowns, 5)

                if reply:
                    await message.reply(reply)
                else:
                    # 最終備用，防止靜音
                    await message.reply(random.choice(self.kobe_quotes))
            return

        # 2. 圖片審判 (請確保有實作 analyze_image 邏輯)
        if message.attachments:
            # 這裡需要調用 analyze_image
            return 

        # 3. 關鍵字/藉口粉碎 (保留邏輯)
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            
        # 4. 🔥 關鍵修復：將控制權交還給指令處理器
        await self.bot.process_commands(message)

    # ==========================================
    # 📊 任務與工具 (簡化)
    # ==========================================
    @tasks.loop(minutes=60)
    async def random_mood(self):
        channel = self.get_broadcast_channel()
        if channel:
            await channel.send(random.choice(self.kobe_quotes))
    
    @tasks.loop(minutes=1)
    async def daily_tasks(self):
        # 這裡應有每日挑戰和午夜結算邏輯 (請確保有實作)
        pass 

    @tasks.loop(minutes=5)
    async def voice_check(self):
        # 這裡應有語音擺爛偵測邏輯 (請確保有實作)
        pass

    def get_broadcast_channel(self):
        if not self.bot.guilds: return None
        guild = self.bot.guilds[0]
        return self.get_text_channel(guild)

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target), guild.text_channels) or guild.text_channels[0]


async def setup(bot):
    await bot.add_cog(Game(bot))

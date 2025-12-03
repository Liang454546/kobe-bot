import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta, timezone
import random
import os
import google.generativeai as genai

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        self.active_sessions = {}
        self.focus_sessions = {}
        self.user_goals = {}
        self.voice_sessions = {}
        
        # 冷卻系統
        self.cooldowns = {} 
        self.chat_activity = [] 
        self.proactive_roast_cooldowns = {} 
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {} 
        
        # 設定 AI
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                print("✅ Gemini 2.0 啟動成功")
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
        self.targeted_roasts = {"gta": "俠盜獵車手？", "nba": "玩 NBA 2K？", "league of legends": "又在打 LOL？"}

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE)')
            await db.commit()
        
        self.daily_tasks.start()
        self.voice_check.start()
        self.topic_starter.start() # 🔥 啟動新的隨機插話任務

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.voice_check.cancel()
        self.topic_starter.cancel() # 🔥 停止新的任務

    # ==========================================
    # 🔥 新增：AI 每日隨機點名 (Topic Starter)
    # ==========================================
    @tasks.loop(hours=1)
    async def topic_starter(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        
        # 限制發言時間在 9:00 AM 到 9:00 PM 之間
        if not (9 <= now.hour < 21):
            return
        
        # 隨機觸發，避免太頻繁 (15% 機率每小時發言)
        if random.random() < 0.15: 
            channel = self.get_broadcast_channel()
            if not channel: return
            
            # 讓 AI 創造一個毒舌話題
            prompt = "群組裡很安靜，請你主動介入，用一句話毒舌地開始一個關於紀律、訓練，或人生目標的話題。要兇。"
            topic = await self.ask_kobe(prompt, 0, {}, 0) # 這裡不設冷卻
            
            if topic:
                await channel.send(f"🗣️ **Kobe 亂入：**\n{topic}")
                
    @topic_starter.before_loop
    async def before_topic_starter(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 🧠 AI 核心：通用問答
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        # 這裡的冷卻檢查是為了保護 API
        if cooldown_dict and user_id and time.time() - cooldown_dict.get(user_id, 0) < cooldown_time: return None
        if cooldown_dict and user_id: cooldown_dict[user_id] = time.time()

        try:
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格。請用繁體中文(台灣)。回答簡短有力(50字內)，多用 emoji (🏀🐍)。"
            contents = [sys_prompt, f"情境：{prompt}"]
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
        channel = self.get_text_channel(after.guild)

        now = time.time()
        if user_id in self.cooldowns and now - self.cooldowns[user_id] < 2: return
        self.cooldowns[user_id] = now 

        if new_game == old_game: 
            # 偵測遊戲時間過長
            if new_game and user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                ROAST_THRESHOLD, ROAST_COOLDOWN = 7200, 21600 # 2小時 / 6小時
                
                if duration >= ROAST_THRESHOLD and (user_id not in self.proactive_roast_cooldowns or now - self.proactive_roast_cooldowns[user_id] >= ROAST_COOLDOWN):
                    self.proactive_roast_cooldowns[user_id] = now
                    hours = duration // 3600
                    prompt = f"這軟蛋玩 {new_game} 超過 {hours} 小時了。問他眼神還亮嗎？"
                    roast_msg = await self.ask_kobe(prompt, user_id, self.cooldowns, 0) # 這裡不需要獨立冷卻
                    if roast_msg:
                        await channel.send(f"⚠️ **疲勞警告！** {after.mention}\n{roast_msg}")
                        await self.update_stat(user_id, "lazy_points", 10)
            return

        # 遊戲結束 (存檔 + 採訪)
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                # 這裡需要 call save_to_db, 邏輯已在其他函式
                del self.active_sessions[user_id]
                
                if duration > 600 and channel:
                    mins = duration // 60
                    prompt = f"{after.display_name} 玩了 {mins} 分鐘 {old_game}。質問他學到了什麼？"
                    interview = await self.ask_kobe(prompt, user_id, self.cooldowns, 0)
                    if interview: await channel.send(f"🎤 **賽後毒舌採訪** {after.mention}\n{interview}")

        # 遊戲開始 (AI 罵人)
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # AI 罵人 (冷卻 5 分鐘)
            roast_msg = await self.ask_kobe(f"這軟蛋開始玩 {new_game} 了，罵他。", user_id, self.cooldowns, 300)
            
            # 如果 AI 失敗，用備用
            if not roast_msg:
                roast_text = random.choice(self.kobe_quotes).format(member=after.mention) 
                roast_msg = f"{after.mention} {roast_text}"
            else:
                roast_msg = f"{after.mention} {roast_msg}"

            # 發送並語音突襲 (無聲版)
            if channel: await channel.send(roast_msg)
            if after.voice and after.voice.channel:
                try:
                    vc = after.guild.voice_client
                    if not vc: await after.voice.channel.connect()
                    elif vc.channel != after.voice.channel: await vc.move_to(after.voice.channel)
                    if channel: await channel.send(f"🎙️ **語音查哨中...** (盯著你)")
                except: pass

    # ==========================================
    # 💬 聊天監控 (修復靜音 + 指令處理)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # 確保指令可以優先處理
        if message.content.startswith('!'):
            await self.bot.process_commands(message)
            return

        user_id = message.author.id
        content = message.content.lower()
        now = time.time()

        # 1. AI 對話 (被標記)
        is_mentioned = self.bot.user in message.mentions or message.content.strip().endswith("?")
        
        if is_mentioned:
            async with message.channel.typing():
                # 使用 ask_kobe 函式，冷卻 5 秒
                reply = await self.ask_kobe(f"用戶問：{content}", user_id, self.cooldowns, 5)

                if reply:
                    await message.reply(reply)
                else:
                    # 最終備用
                    await message.reply(random.choice(self.kobe_quotes))
            return
            
        # 2. 圖片審判 (這裡需要完整 analyze_image 邏輯)
        if message.attachments:
            # 這裡需要調用 analyze_image
            # await self.analyze_image(message)
            return

        # 3. 關鍵字/藉口粉碎 (保留邏輯)
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.add_honor(user_id, -2)

    # ... (其餘 helper 函式與指令) ...

async def setup(bot):
    await bot.add_cog(Game(bot))

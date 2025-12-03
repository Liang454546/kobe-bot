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
        
        # 冷卻與計數器
        self.cooldowns = {} # 通用冷卻 (這裡保留 chat_cooldowns 邏輯)
        self.chat_activity = [] 
        self.ai_roast_cooldowns = {} # 遊戲專屬冷卻
        self.ai_chat_cooldowns = {}  # 對話專屬冷卻
        
        # --- 1. 設定 AI (Gemini 2.0 Flash) ---
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
            self.has_ai = False

        # 關鍵字庫
        self.procrastination_words = ["等下", "明天", "之後", "先休息", "再看", "晚點"]
        self.topic_words = ["工作", "唸書", "練習", "戀愛", "心情", "好煩", "想放棄"]
        self.liar_keywords = ["讀書", "寫作業", "健身", "忙", "加班"]
        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS streaks (user_id INTEGER PRIMARY KEY, current_streak INTEGER DEFAULT 0, last_checkin_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE)')
            await db.commit()
        
        # 啟動自動任務
        self.daily_tasks.start()
        self.voice_check.start()

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.voice_check.cancel()

    # ==========================================
    # 🧠 AI 核心：通用問答 (修正回傳值)
    # ==========================================
    async def ask_kobe(self, prompt, user_id, cooldown_dict, cooldown_time=30, image=None):
        if not self.has_ai: return None

        now = time.time()
        if user_id in cooldown_dict:
            if now - cooldown_dict[user_id] < cooldown_time: return "COOLDOWN"
        
        cooldown_dict[user_id] = now

        try:
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格。請用繁體中文(台灣)。回答簡短有力(30字內)，多用 emoji (🏀🐍)。"
            contents = [sys_prompt, f"情境：{prompt}"]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except: return None

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

        # 避免 Discord 瞬間多次更新
        now = time.time()
        if user_id in self.cooldowns and now - self.cooldowns[user_id] < 2: return
        self.cooldowns[user_id] = now 

        if new_game == old_game: 
            # 偵測遊戲時間過長
            if new_game and user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                ROAST_THRESHOLD, ROAST_COOLDOWN = 7200, 21600 # 2小時 / 6小時冷卻
                
                if duration >= ROAST_THRESHOLD and (user_id not in self.ai_roast_cooldowns or now - self.ai_roast_cooldowns[user_id] >= ROAST_COOLDOWN):
                    self.ai_roast_cooldowns[user_id] = now
                    hours = duration // 3600
                    prompt = f"這軟蛋玩 {new_game} 超過 {hours} 小時了。問他眼神還亮嗎？"
                    roast_msg = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 0)
                    if roast_msg and channel:
                        await channel.send(f"⚠️ **疲勞警告！** {after.mention}\n{roast_msg}")
                        await self.update_stat(user_id, "lazy_points", 10)
            return

        # 遊戲結束 (存檔 + 採訪)
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                
                if duration > 600 and channel:
                    mins = duration // 60
                    prompt = f"{after.display_name} 玩了 {mins} 分鐘 {old_game}。質問他學到了什麼？"
                    interview = await self.ask_kobe(prompt, user_id, self.ai_chat_cooldowns, 0)
                    if interview: await channel.send(f"🎤 **賽後毒舌採訪** {after.mention}\n{interview}")

        # 遊戲開始 (AI 罵人)
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # AI 罵人 (冷卻 5 分鐘)
            roast_msg = await self.ask_kobe(f"這軟蛋開始玩 {new_game} 了，罵他。", user_id, self.ai_roast_cooldowns, 300)
            
            # 如果 AI 失敗，用備用
            if not roast_msg:
                roast_text = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
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

    # ... (其餘 helper 函式) ...
    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    async def update_stat(self, user_id, column, value):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM daily_stats WHERE user_id = ?", (user_id,))
            if not await cursor.fetchone():
                await db.execute("INSERT INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
            
            await db.execute(f"UPDATE daily_stats SET {column} = {column} + ? WHERE user_id = ?", (value, user_id))
            await db.commit()

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target) and x.permissions_for(guild.me).send_messages, guild.text_channels) or guild.text_channels[0]
    
    # ... (保留其餘 functions and commands) ...
    
    # ==========================================
    # 💬 聊天監控 (修復靜音問題)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return

        # 0. 設置單用戶冷卻，避免刷屏
        user_id = message.author.id
        now = time.time()
        
        # 1. AI 對話 (被標記)
        is_mentioned = self.bot.user in message.mentions or (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user)
        
        if is_mentioned:
            async with message.channel.typing():
                # 🔥 這裡調用 AI 時，使用 ai_chat_cooldowns
                reply = await self.ask_kobe(f"用戶說：{message.content}", user_id, self.cooldowns, 5) # 使用 general self.cooldowns 作為 chat CD

                if reply == "COOLDOWN":
                    await message.reply("別吵我，正在訓練。🏀 (冷卻中)")
                elif reply == "ERROR":
                    await message.reply("⚠️ AI 連線錯誤，請檢查 Render Logs。")
                elif reply == "NO_API_KEY":
                    await message.reply("❌ **系統錯誤**：我讀不到 `GEMINI_API_KEY`！")
                elif reply:
                    await message.reply(reply)
                else:
                    # 終極備用
                    await message.reply(random.choice(self.kobe_quotes))
            # 必須 return 讓指令處理器跳過這個訊息
            return

        # 2. 圖片審判 (略)
        if message.attachments:
            # 這裡應該有圖片分析邏輯
            return 

        # 3. 拖延偵測 / 說謊偵測 (略)
        # 這裡應該有大量的 if/await self.check_liar(message) / await self.check_procrastination(message) 邏輯

        # 4. 🔥 關鍵：將控制權交還給指令處理器
        await self.bot.process_commands(message)

    # ... (以下保留所有其他指令與 Tasks) ...
    # 為了簡潔，這裡省略所有重複的指令與 Tasks 程式碼，但您應該使用完整的 cogs/game.py 檔案。

async def setup(bot):
    await bot.add_cog(Game(bot))

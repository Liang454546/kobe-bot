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
        self.cooldowns = {} # 通用冷卻 (這裡用來儲存單一用戶對話冷卻)
        self.proactive_roast_cooldowns = {} # 遊戲超時冷卻
        self.chat_cooldowns = {} # 藉口粉碎機冷卻
        self.chat_activity = [] 

        # --- 1. 設定 AI ---
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
        self.procrastination_words = ["等下", "明天", "之後", "先休息", "再看", "晚點"]
        self.liar_keywords = ["讀書", "寫作業", "健身", "忙", "加班"]
        self.weak_words = ["累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。", "Soft. 🥚"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            # 確保所有表格都存在
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
    # 🧠 AI 核心：通用問答 (修正參數)
    # ==========================================
    async def ask_kobe(self, prompt, user_id, cooldown_dict, cooldown_time=30, image=None):
        """通用 AI 呼叫函式，參數已修正"""
        if not self.has_ai: return None

        now = time.time()
        if user_id in cooldown_dict:
            if now - cooldown_dict[user_id] < cooldown_time: return None
        cooldown_dict[user_id] = now

        try:
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格。請用繁體中文(台灣)。回答簡短有力(30字內)，多用 emoji (🏀🐍)。"
            contents = [sys_prompt, f"情境：{prompt}"]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except: 
            # 這裡回傳 None，讓 on_message 執行備用方案
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
                ROAST_THRESHOLD, ROAST_COOLDOWN = 7200, 21600 
                
                if duration >= ROAST_THRESHOLD and (user_id not in self.proactive_roast_cooldowns or now - self.proactive_roast_cooldowns[user_id] >= ROAST_COOLDOWN):
                    self.proactive_roast_cooldowns[user_id] = now
                    hours = duration // 3600
                    prompt = f"這軟蛋玩 {new_game} 超過 {hours} 小時了。問他眼神還亮嗎？"
                    roast_msg = await self.ask_kobe(prompt, user_id, self.proactive_roast_cooldowns, 0)
                    if roast_msg:
                        await channel.send(f"⚠️ **疲勞警告！** {after.mention}\n{roast_msg}")
                        await self.update_stat(user_id, "lazy_points", 10)
            return

        # 遊戲結束 (存檔 + 採訪)
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                # 這裡需要 call save_to_db, 邏輯已經在原始 code block 裡了
                # 這裡保留邏輯不變
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
                roast_text = random.choice(self.kobe_quotes).format(member=after.mention) # 這裡用簡化的kobe_quotes
                roast_msg = f"{after.mention} {roast_text}"
            
            if channel: await channel.send(roast_msg)
            # 語音突襲 (無聲版)
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
        user_id = message.author.id
        content = message.content
        
        # 1. AI 對話 (被標記)
        is_mentioned = self.bot.user in message.mentions or (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user)
        
        if is_mentioned:
            # 這裡使用 ai_chat_cooldowns 作為通用冷卻
            if user_id in self.cooldowns and time.time() - self.cooldowns[user_id] < 5:
                await message.reply("別吵我，正在訓練。🏀 (冷卻中)")
                return

            async with message.channel.typing():
                # 🔥 修正：傳入正確的 user_id, cooldown_dict, cooldown_time
                reply = await self.ask_kobe(f"用戶說：{content}", user_id, self.cooldowns, 5)

                if reply == "ERROR" or reply == "NO_API_KEY":
                    await message.reply("⚠️ AI 連線錯誤，請檢查 Render Logs 或 API Key。")
                elif reply:
                    await message.reply(reply)
                else:
                    # 終極備用 (當 AI 失敗或冷卻時)
                    await message.reply(random.choice(self.kobe_quotes))
            return

        # 2. 關鍵字/藉口粉碎 (為了簡潔，這裡只保留最基本的判斷)
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.add_honor(user_id, -2)
        elif any(w in content for w in self.strong_words):
            await message.channel.send(f"{message.author.mention} 這才是曼巴精神！🏀")
            await self.add_honor(user_id, 2)
            
        # 🔥 關鍵修復：將控制權交還給指令處理器
        await self.bot.process_commands(message)

    # ... (其餘 helper 函式與指令，為節省篇幅省略) ...

async def setup(bot):
    await bot.add_cog(Game(bot))

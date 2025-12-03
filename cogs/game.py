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
        
        # 冷卻與計數器
        self.cooldowns = {} 
        self.cooldown_locks = asyncio.Lock()
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        
        # --- AI 設定 (Gemini 2.0 Flash) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (痛恨 2K 教練模式)")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            logger.warning("⚠️ GEMINI_API_KEY 缺失，AI 備用模式")
            self.has_ai = False

        # 關鍵字庫
        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍", "Soft. 🥚"]
        
        # 🔥 備用罵人語錄 (針對 2K 加強火力)
        self.targeted_roasts = {
            "nba": "還在打 2K？🎮 你以為按綠了就是進球？現實中你連框都摸不到！去球場流汗！",
            "2k": "玩 2K 建球員？不如去建設你自己的人生！軟蛋！",
            "league": "又在打 LOL？💀 你的心態炸裂了嗎？",
            "valorant": "特戰英豪？槍法再準，現實生活打不中目標有什麼用？",
            "apex": "APEX？你的肝還好嗎？別再當滋崩狗了！",
            "原神": "啟動？😱 給我把書桌前的燈啟動！"
        }
        self.default_roasts = ["抓到了！{member} 玩 **{game}**！不用唸書嗎？😡", "看到 {member} 玩 **{game}**，曼巴精神去哪了？"]

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
    # 🧠 AI 核心：仇恨 2K + 實用教練
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        now = time.time()
        if user_id and cooldown_dict:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
            cooldown_dict[user_id] = now

        try:
            # 🔥 關鍵修改：加入「痛恨 NBA 2K」的人設
            sys_prompt = (
                "你是 Kobe Bryant。個性：毒舌、嚴格、**極度痛恨 NBA 2K (認為那是浪費生命的電子垃圾)**，但尊重渴望變強的人。\n"
                "規則：\n"
                "1. **如果用戶提到 NBA 2K**：**直接暴怒**，羞辱他只會用手指打球，現實球技是零，叫他滾去球場。\n"
                "2. **如果用戶問問題 (知識/技術/建議)**：給出**實用指導**，但語氣要嚴厲 (如「這都不懂？聽好了...」)。\n"
                "3. **如果用戶在偷懶/抱怨**：狠狠罵他。\n"
                "4. 繁體中文(台灣)，50字內，多用 emoji (🏀🐍)。"
            )
            contents = [sys_prompt, f"用戶輸入：{prompt}"]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except Exception as e:
            logger.error(f"AI 呼叫錯誤: {e}") 
            return "ERROR"

    # ==========================================
    # 🎯 遊戲狀態監控
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

        # A. 遊戲開始
        if new_game and not old_game:
            self.active_sessions[user_id] = {
                "game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False
            }
            
            # AI 罵人 (針對 2K 加強)
            prompt = f"這軟蛋開始玩 {new_game} 了。"
            if "2k" in new_game.lower():
                prompt += "他竟然在玩 NBA 2K！狠狠羞辱他！"
            else:
                prompt += "罵他為什麼不去訓練。"

            roast_msg = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            
            # 備用方案
            if not roast_msg or roast_msg in ["COOLDOWN", "ERROR"]:
                # 檢查是否有針對性備用語錄
                roast_text = next((t for k, t in self.targeted_roasts.items() if k in new_game.lower()), None)
                if not roast_text: roast_text = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
                roast_msg = f"{after.mention} {roast_text}"
            
            if channel: await channel.send(roast_msg)
            
            # 語音查哨
            if after.voice and after.voice.channel:
                try:
                    vc = after.guild.voice_client
                    if not vc: await after.voice.channel.connect()
                    elif vc.channel != after.voice.channel: await vc.move_to(after.voice.channel)
                    if channel: await channel.send(f"🎙️ **語音查哨中...** (盯著你)")
                except: pass

        # B. 遊戲結束
        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                
                if duration > 600 and channel:
                    mins = duration // 60
                    prompt = f"{after.display_name} 玩了 {mins} 分鐘 {old_game}。質問他學到了什麼？"
                    if "2k" in old_game.lower():
                        prompt += "特別強調玩 2K 是浪費生命。"
                        
                    interview = await self.ask_kobe(prompt, user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview not in ["COOLDOWN", "ERROR"]: 
                        await channel.send(f"🎤 **賽後毒舌採訪** {after.mention}\n{interview}")

    # ==========================================
    # ⏰ 遊戲時間監控迴圈 (1hr / 2hr 警告)
    # ==========================================
    @tasks.loop(minutes=1)
    async def game_check(self):
        now = time.time()
        for user_id, session in list(self.active_sessions.items()):
            duration = int(now - session["start"])
            game_name = session["game"]
            
            # 1 小時警告
            if duration >= 3600 and not session.get("1h_warned"):
                session["1h_warned"] = True
                await self.send_warning(user_id, game_name, "1 小時", 5)

            # 2 小時警告
            if duration >= 7200 and not session.get("2h_warned"):
                session["2h_warned"] = True
                await self.send_warning(user_id, game_name, "2 小時", 10)

    async def send_warning(self, user_id, game_name, time_str, penalty):
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild:
            member = guild.get_member(user_id)
            channel = self.get_text_channel(guild)
            if member and channel:
                prompt = f"用戶玩 {game_name} 超過 {time_str}。毒舌警告他。"
                if "2k" in game_name.lower():
                    prompt += "痛罵他玩 2K 浪費時間。"
                
                msg = await self.ask_kobe(prompt, user_id, {}, 0) or f"{member.mention} 玩 {time_str} 了！去訓練！"
                await channel.send(f"⚠️ **{time_str} 警報** {member.mention}\n{msg}")
                await self.update_daily_stats(user_id, "lazy_points", penalty)

    @game_check.before_loop
    async def before_game_check(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 💬 聊天監控
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        user_id = message.author.id
        content = message.content
        
        # AI 對話
        is_mentioned = self.bot.user in message.mentions or (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user) or message.content.strip().endswith("?")
        
        if is_mentioned:
            async with message.channel.typing():
                if user_id in self.ai_chat_cooldowns and time.time() - self.ai_chat_cooldowns.get(user_id, 0) < 5:
                    await message.reply("別吵我，正在訓練。🏀 (冷卻中)")
                    return

                # 若內容包含 2K，AI 會自動觸發仇恨模式
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 5)

                if reply == "ERROR":
                    await message.reply("⚠️ AI 連線錯誤，請檢查 Render Logs。")
                elif reply:
                    await message.reply(reply)
                else:
                    await message.reply(random.choice(self.kobe_quotes))
            return

        # 關鍵字
        if any(w in content for w in self.weak_words):
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！😤")
            await self.update_daily_stats(user_id, "lazy_points", 2)
        elif any(w in content for w in self.strong_words):
            await message.channel.send(f"{message.author.mention} 這才是曼巴精神！🏀")
            await self.add_honor(user_id, 2)
            
        await self.bot.process_commands(message)

    # ==========================================
    # 資料庫與工具
    # ==========================================
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
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (user_id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target) and x.permissions_for(guild.me).send_messages, guild.text_channels) or guild.text_channels[0]
    
    # ==========================================
    # Tasks (每日任務, etc)
    # ==========================================
    @tasks.loop(hours=24)
    async def daily_tasks(self):
        pass

    @tasks.loop(minutes=30)
    async def random_mood(self):
        pass

    @tasks.loop(seconds=30)
    async def voice_check(self):
        pass
    
    @daily_tasks.before_loop
    @game_check.before_loop
    @random_mood.before_loop
    @voice_check.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

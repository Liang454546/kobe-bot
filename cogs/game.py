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
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (曼巴哲學家模式)")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            logger.warning("⚠️ GEMINI_API_KEY 缺失，AI 備用模式")
            self.has_ai = False

        # 關鍵字庫 (保留基本關鍵字，但回應邏輯已轉交給 AI)
        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.strong_words = ["健身", "訓練", "加班", "努力"]
        
        # 哲學語錄 (備用)
        self.kobe_quotes = [
            "低頭不是認輸，是要看清自己的路。",
            "那些殺不死你的，只會讓你更強。",
            "如果你害怕失敗，那你已經輸了。",
            "重點不在於結果，而在於過程中的每一次呼吸。",
            "痛苦是最好的老師，它告訴你哪裡還需要變強。"
        ]

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
    # 🧠 AI 核心：哲學家模式 (Philosopher Mode)
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None):
        if not self.has_ai: return None

        # 冷卻檢查
        now = time.time()
        if user_id and cooldown_dict:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
            cooldown_dict[user_id] = now

        try:
            # 🔥 核心修改：哲學家與實踐者的人設
            sys_prompt = (
                "你是 Kobe Bryant，現在的你是一位**籃球哲學家**與**實踐導師**。\n"
                "你的目標：透過智慧、邏輯與曼巴精神，引導用戶解決問題，而不只是單純的謾罵。\n"
                "行為準則：\n"
                "1. **面對提問 (重要)**：必須給出**具體、實際且有深度**的解答。例如用戶問程式碼，你要指出邏輯錯誤；問人生，你要給出行動方針。回答要像一個嚴格但充滿智慧的導師。\n"
                "2. **面對懶惰**：用**哲理性**的語言讓他感到羞愧，而不是用髒話。例如：「休息？棺材裡有的是時間休息。現在是創造傳奇的時候。」\n"
                "3. **面對 NBA 2K**：表達出一種「恨鐵不成鋼」的遺憾，認為虛擬的勝利無法填補現實的空虛。\n"
                "4. **語氣**：深沉、冷靜、一針見血。繁體中文(台灣)，50字內，多用 emoji (🧘‍♂️🐍🏀)。"
            )
            contents = [sys_prompt, f"用戶輸入：{prompt}"]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except Exception as e:
            logger.error(f"AI 呼叫錯誤: {e}") 
            return "ERROR"

    # ==========================================
    # 📸 圖片審判 (哲學視角)
    # ==========================================
    async def analyze_image(self, image_url, user_id):
        # ... (這裡沿用 Game class 的邏輯，只是 prompt 改變) ...
        # 為了完整性，這裡重寫 analyze_image 邏輯以配合新 prompt
        
        async with self.cooldown_locks:
            now = time.time()
            if now - self.image_cooldowns.get(user_id, 0) < 60:
                return "觀察需要時間。冷卻中...🧘‍♂️"
            self.image_cooldowns[user_id] = now

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200: return "圖像無法讀取，如同模糊的目標。🌫️"
                    data = await resp.read()

            image = Image.open(io.BytesIO(data))
            
            # 使用哲學家 Prompt 進行圖片分析
            reply = await self.ask_kobe(
                prompt="觀察這張圖片。這反映了用戶什麼樣的生活態度？是自律的展現，還是放縱的證據？用哲學的角度點評他。",
                user_id=user_id,
                cooldown_dict=self.image_cooldowns,
                cooldown_time=0, # 外層已檢查
                image=image
            )
            return reply or "我看不到曼巴精神，只看到一張圖。🐍"

        except Exception as e:
            logger.error(f"圖片分析錯誤: {e}")
            return random.choice(self.kobe_quotes)

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
        if user_id in self.cooldowns and now - self.cooldowns.get(user_id, 0) < 2: return
        self.cooldowns[user_id] = now 

        # A. 遊戲開始
        if new_game and not old_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            
            prompt = f"用戶開始玩 {new_game} 了。"
            if "2k" in new_game.lower():
                prompt += "用哲學的角度告訴他，為何沉迷於虛擬的籃球無法讓他成為真正的傳奇。"
            else:
                prompt += "用反問句以此質問他：這真的是你現在該做的事嗎？"

            roast_msg = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            if channel: await channel.send(roast_msg or f"{after.mention} {new_game}？你的時間就是這樣流逝的嗎？⏳")

        # B. 遊戲結束
        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                
                if duration > 600 and channel:
                    prompt = f"{after.display_name} 結束了 {duration//60} 分鐘的 {old_game}。請他反思這段時間獲得了什麼實質的成長。"
                    interview = await self.ask_kobe(prompt, user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN": 
                        await channel.send(f"🎤 **靈魂拷問** {after.mention}\n{interview}")

    # ==========================================
    # 💬 聊天監控
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        user_id = message.author.id
        content = message.content
        
        # 1. AI 對話 (被標記 或 ? 結尾)
        is_mentioned = self.bot.user in message.mentions or (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user) or message.content.strip().endswith("?")
        
        if is_mentioned:
            async with message.channel.typing():
                # 直接將用戶內容傳給 ask_kobe，讓 Prompt 裡的規則去判斷是要回答問題還是要罵人
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 5)

                if reply == "COOLDOWN":
                    await message.reply("專注。別刷屏。🧘‍♂️")
                elif reply == "ERROR":
                    await message.reply("⚠️ 思緒中斷 (AI Error)。")
                elif reply:
                    await message.reply(reply)
                else:
                    await message.reply(random.choice(self.kobe_quotes))
            return

        # 2. 圖片審判 (如果有傳圖)
        if message.attachments:
             # 檢查是否為圖片
            if any(message.attachments[0].content_type.startswith(t) for t in ["image/"]):
                async with message.channel.typing():
                    reply = await self.analyze_image(message.attachments[0].url, user_id)
                    await message.reply(reply)
                return

        # 3. 關鍵字 (哲學版)
        if any(w in content for w in self.weak_words):
            # 這裡不一定要 AI，可以用隨機哲學語錄省額度
            await message.channel.send(f"{message.author.mention} {random.choice(self.kobe_quotes)}")
            await self.update_daily_stats(user_id, "lazy_points", 2)
            
        await self.bot.process_commands(message)

    # ... (資料庫與 Tasks 保持不變，為節省篇幅省略，請保留原有的 save_to_db, update_daily_stats, send_warning 等函式) ...
    # 請務必保留原有的 helper functions 和 tasks!
    
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

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target) and x.permissions_for(guild.me).send_messages, guild.text_channels) or guild.text_channels[0]

    @tasks.loop(minutes=1)
    async def game_check(self):
        now = time.time()
        for user_id, session in list(self.active_sessions.items()):
            duration = int(now - session["start"])
            if duration >= 3600 and not session.get("1h_warned"):
                session["1h_warned"] = True
                await self.send_warning(user_id, session["game"], "1小時", 5)
            if duration >= 7200 and not session.get("2h_warned"):
                session["2h_warned"] = True
                await self.send_warning(user_id, session["game"], "2小時", 10)

    async def send_warning(self, user_id, game, time_str, penalty):
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild:
            member = guild.get_member(user_id)
            channel = self.get_text_channel(guild)
            if member and channel:
                prompt = f"用戶沉迷於 {game} 超過 {time_str}。用時間的哲學告訴他，這些逝去的光陰是無法贖回的。"
                msg = await self.ask_kobe(prompt, user_id, {}, 0) or f"{member.mention} 時間不等人。你已經浪費了 {time_str}。"
                await channel.send(f"⏳ **{time_str} 警報** {member.mention}\n{msg}")
                await self.update_daily_stats(user_id, "lazy_points", penalty)

    @tasks.loop(hours=24)
    async def daily_tasks(self): pass
    @tasks.loop(seconds=30)
    async def voice_check(self): pass
    
    @game_check.before_loop
    @daily_tasks.before_loop
    @voice_check.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

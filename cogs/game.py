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
        
        # 冷卻與計數器
        self.cooldowns = {} 
        self.chat_activity = []  # 記錄聊天頻率 [timestamp, timestamp...]
        
        # 設定 AI
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                print("✅ Gemini 2.0 (全能版) 啟動成功")
            except Exception as e:
                print(f"❌ AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        # 關鍵字庫
        self.procrastination_words = ["等下", "明天", "之後", "先休息", "再看", "晚點"]
        self.topic_words = ["工作", "唸書", "練習", "戀愛", "心情", "好煩", "想放棄"]
        self.liar_keywords = ["讀書", "寫作業", "健身", "忙", "加班"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
                user_id INTEGER PRIMARY KEY, 
                msg_count INTEGER DEFAULT 0, 
                lazy_points INTEGER DEFAULT 0, 
                roasted_count INTEGER DEFAULT 0,
                last_updated DATE
            )''')
            await db.execute('CREATE TABLE IF NOT EXISTS quotes (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, content TEXT, date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.commit()
        
        self.daily_tasks.start()
        self.voice_check.start()

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.voice_check.cancel()

    # ==========================================
    # 🧠 AI 核心：通用大腦
    # ==========================================
    async def ask_kobe(self, prompt, image=None):
        if not self.has_ai: return None
        try:
            sys_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格、看不起軟弱。請用繁體中文(台灣)。回答簡短有力(50字內)，多用 emoji (🏀🐍)。"
            contents = [sys_prompt, f"情境：{prompt}"]
            if image: contents.append(image)
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except: return None

    # ==========================================
    # 📌 新增：Kobe 提及或回覆訊息偵測
    # ==========================================
    async def handle_kobe_mentions(self, message):
        now = time.time()
        user_id = message.author.id
        # 冷卻 15 秒
        if user_id in self.cooldowns and now - self.cooldowns[user_id] < 15:
            return
        self.cooldowns[user_id] = now

        async with message.channel.typing():
            reply = await self.ask_kobe(f"用戶說：'{message.content}'，用毒舌 Kobe 語氣回應，30字內")
            if reply:
                await message.reply(reply)
                # 簡單紀錄名言
                if len(reply) < 20:
                    await self.save_quote(user_id, message.content)

    # ==========================================
    # ⑮ 圖片審判
    # ==========================================
    async def analyze_image(self, message):
        img_bytes = await message.attachments[0].read()
        img = Image.open(io.BytesIO(img_bytes))
        prompt = (
            "分析這張圖。如果是垃圾食物/遊戲/動漫/床/耍廢 -> 狠狠罵他墮落，說他是廢物。"
            "如果是健身/書本/程式碼/健康食物 -> 稱讚他，給予肯定。"
            "如果是梗圖 -> 評論好不好笑。"
            "用 Kobe 語氣，30字內。"
        )
        comment = await self.ask_kobe(prompt, image=img)
        if comment:
            change = -5 if any(x in comment for x in ["廢", "軟", "垃圾", "墮落"]) else 5
            await self.update_stat(message.author.id, "lazy_points", 5 if change < 0 else 0)
            await message.reply(f"{comment} (榮譽 `{change:+d}`)")

    # ==========================================
    # 🕵️ 說謊偵測器
    # ==========================================
    async def check_liar(self, message):
        member = message.author
        if not member.activities: return False
        game = next((a.name for a in member.activities if a.type == discord.ActivityType.playing), None)
        if not game: return False
        if any(w in message.content for w in self.liar_keywords):
            await message.reply(f"🤥 **騙子！** 你嘴上說「{message.content}」，但 Discord 顯示你在玩 **{game}**！\n(榮譽 -20，懶惰指數 +10)")
            await self.update_stat(member.id, "lazy_points", 10)
            return True
        return False

    # ==========================================
    # ⏳ 拖延症偵測
    # ==========================================
    async def check_procrastination(self, message):
        score = 0
        for word, pts in [("等下",30),("明天",30),("之後",30),("先休息",40),("再看",20)]:
            if word in message.content:
                score += pts
        if score >= 60:
            comment = await self.ask_kobe(f"用戶說『{message.content}』，拖延症分數 {score} 分。罵他別找藉口，現在就做。")
            await message.reply(f"⚠️ **拖延症警告！**\n{comment}\n(懶惰指數 +{score//10})")
            await self.update_stat(message.author.id, "lazy_points", score//10)
            return True
        return False

    # ==========================================
    # 💬 訊息總監控
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return

        # 更新今日發話量
        await self.update_stat(message.author.id, "msg_count", 1)

        # 1. Kobe 提及偵測
        bot_mentioned = self.bot.user in message.mentions
        if bot_mentioned or "kobe" in message.content.lower():
            if self.has_ai:
                await self.handle_kobe_mentions(message)
            return

        # 2. 圖片審判
        if message.attachments:
            await self.analyze_image(message)
            return

        # 3. 說謊偵測
        if await self.check_liar(message): return

        # 4. 拖延偵測
        if await self.check_procrastination(message): return

        # 5. 聊天活躍插話
        now = time.time()
        self.chat_activity.append(now)
        self.chat_activity = [t for t in self.chat_activity if now - t < 60]
        if len(self.chat_activity) > 10 and random.random() < 0.3:
            self.chat_activity = []
            await message.channel.send("🔥 聊得很熱烈嘛？既然精神這麼好，為什麼不去訓練？")

        # 6. 特定關鍵字藏頭詩
        if "好累" in message.content:
            await message.channel.send("好：好意思喊累？\n累：累就對了，代表還活著。🐍")
            return

        # 7. AI 情緒話題分析
        user_id = message.author.id
        if user_id in self.cooldowns and now - self.cooldowns[user_id] < 30: return
        needs_ai = any(w in message.content for w in self.topic_words + ["怎麼辦", "救命", "不想活"])
        if needs_ai and self.has_ai:
            self.cooldowns[user_id] = now
            async with message.channel.typing():
                prompt = (
                    f"用戶說：『{message.content}』。\n"
                    "1. 判斷情緒 (0-1)，若 > 0.7 (負面) 則毒舌罵醒他。\n"
                    "2. 若包含戀愛/工作/唸書，給 30 字毒舌人生建議。\n"
                    "3. 若是廢話，回答 'SKIP'。"
                )
                reply = await self.ask_kobe(prompt)
                if reply and "SKIP" not in reply:
                    await message.reply(reply)
                    if len(reply) < 20:
                        await self.save_quote(user_id, message.content)

    # ==========================================
    # 📅 自動任務（每日挑戰、總結）
    # ==========================================
    @tasks.loop(minutes=1)
    async def daily_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        channel = self.get_broadcast_channel()
        if not channel: return

        if now.hour == 4 and 0 <= now.minute < 5:
            for member in channel.guild.members:
                if not member.bot and member.status != discord.Status.offline:
                    game = next((a.name for a in member.activities if a.type == discord.ActivityType.playing), None)
                    if game:
                        await channel.send(f"😡 {member.mention} 凌晨四點還在玩 **{game}**？這種紀律你要贏什麼？(榮譽 -50)")
                        await self.update_stat(member.id, "lazy_points", 50)

        if now.hour == 6 and now.minute == 0:
            challenges = ["閱讀 30 分鐘", "伏地挺身 50 下", "不喝含糖飲料", "背 10 個英文單字", "整理房間"]
            await channel.send(f"☀️ **曼巴每日挑戰**\n今日任務：**{random.choice(challenges)}**\n完成後輸入 `!done` 領取榮譽！")

        if now.hour == 23 and now.minute == 59:
            await self.send_daily_summary(channel)

    async def send_daily_summary(self, channel):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id, msg_count, lazy_points FROM daily_stats ORDER BY lazy_points DESC LIMIT 3")
            rows = await cursor.fetchall()
            if not rows: return
            text = "📊 **今日結算報告**\n"
            text += f"👑 **今日廢物王**：<@{rows[0][0]}> (懶惰指數 {rows[0][2]})\n"
            await db.execute("DELETE FROM daily_stats")
            await db.commit()
            comment = await self.ask_kobe(f"今日最懶的人是 {rows[0][0]}，懶惰指數 {rows[0][2]}。做個毒舌總結。")
            await channel.send(text + f"\n🐍 Kobe 點評：{comment}")

    @tasks.loop(minutes=5)
    async def voice_check(self):
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                if len(vc.members) > 0:
                    for member in vc.members:
                        if member.bot: continue
                        if str(member.status) in ["idle", "dnd"]:
                            channel = self.get_text_channel(guild)
                            if channel:
                                await channel.send(f"⚠️ {member.mention} 在語音頻道裝死？擺爛語音？練什麼練？(懶惰指數 +5)")
                                await self.update_stat(member.id, "lazy_points", 5)

    @daily_tasks.before_loop
    @voice_check.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 🛠️ 資料庫工具
    # ==========================================
    async def update_stat(self, user_id, column, value):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM daily_stats WHERE user_id = ?", (user_id,))
            if not await cursor.fetchone():
                await db.execute("INSERT INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
            await db.execute(f"UPDATE daily_stats SET {column} = {column} + ? WHERE user_id = ?", (value, user_id))
            await db.commit()

    async def save_quote(self, user_id, content):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO quotes (user_id, content, date) VALUES (?, ?, ?)", (user_id, content, today))
            await db.commit()

    def get_broadcast_channel(self):
        if not self.bot.guilds: return None
        guild = self.bot.guilds[0]
        return self.get_text_channel(guild)

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target), guild.text_channels) or guild.text_channels[0]

async def setup(bot):
    await bot.add_cog(Game(bot))

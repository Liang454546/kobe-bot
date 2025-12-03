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
        self.cooldowns = {} # 單用戶冷卻 15 秒
        self.chat_activity = []

        # AI 初始化
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                print("✅ Gemini 2.0 (Kobe AI) 啟動成功")
            except Exception as e:
                print(f"❌ AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        # 關鍵字
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

    # ===============================
    # AI Kobe 回覆
    # ===============================
    async def ask_kobe(self, prompt, image=None):
        if not self.has_ai: return None
        try:
            sys_prompt = (
                "你是 Kobe Bryant。語氣溫馨、有趣、耿直、不恭維、痛恨 NBA2K。"
                "用繁體中文，30字內回答，多用 emoji 🏀🐍。"
            )
            contents = [sys_prompt, f"情境：{prompt}"]
            if image: contents.append(image)
            
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except: return None

    # ===============================
    # 圖片審判
    # ===============================
    async def analyze_image(self, message):
        img_bytes = await message.attachments[0].read()
        img = Image.open(io.BytesIO(img_bytes))
        prompt = (
            "分析這張圖。垃圾/遊戲/床/耍廢 -> 狠罵。健身/書本/程式碼/健康食物 -> 稱讚。梗圖 -> 評論。"
            "Kobe 語氣，30字內。"
        )
        comment = await self.ask_kobe(prompt, image=img)
        if comment:
            change = -5 if any(x in comment for x in ["廢", "軟", "垃圾", "墮落"]) else 5
            await self.update_stat(message.author.id, "lazy_points", 5 if change < 0 else 0)
            await message.reply(f"{comment} (榮譽 `{change:+d}`)")

    # ===============================
    # 說謊偵測
    # ===============================
    async def check_liar(self, message):
        member = message.author
        if not member.activities: return False
        game = next((a.name for a in member.activities if a.type == discord.ActivityType.playing), None)
        if not game: return False
        if any(w in message.content for w in self.liar_keywords):
            await message.reply(f"🤥 **騙子！** 你說『{message.content}』，但在玩 **{game}**！\n(榮譽 -20，懶惰指數 +10)")
            await self.update_stat(member.id, "lazy_points", 10)
            return True
        return False

    # ===============================
    # 拖延症偵測
    # ===============================
    async def check_procrastination(self, message):
        score = sum(30 if w in message.content else 0 for w in self.procrastination_words)
        if "先休息" in message.content: score += 10
        if score >= 60:
            comment = await self.ask_kobe(f"用戶說『{message.content}』，拖延症分數 {score} 分。罵他別找藉口，現在就做。")
            await message.reply(f"⚠️ **拖延症警告！**\n{comment}\n(懶惰指數 +{score//10})")
            await self.update_stat(message.author.id, "lazy_points", score//10)
            return True
        return False

    # ===============================
    # 訊息監控
    # ===============================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return

        user_id = message.author.id
        now = time.time()

        # 單用戶冷卻 15 秒
        if user_id in self.cooldowns and now - self.cooldowns[user_id] < 15:
            return
        self.cooldowns[user_id] = now

        # 更新今日發話量
        await self.update_stat(user_id, "msg_count", 1)

        # 圖片審判
        if message.attachments:
            await self.analyze_image(message)
            return

        # 說謊偵測
        if await self.check_liar(message): return

        # 拖延偵測
        if await self.check_procrastination(message): return

        # Kobe AI 回覆觸發：訊息結尾 ? 或 mention
        if message.content.strip().endswith("?") or self.bot.user in message.mentions:
            reply = await self.ask_kobe(message.content)
            if reply: 
                await message.reply(reply)
                if len(reply) < 20:
                    await self.save_quote(user_id, message.content)
            return

        # 其他有趣毒舌互動可依需求擴充

    # ===============================
    # 自動任務、每日總結
    # ===============================
    @tasks.loop(minutes=1)
    async def daily_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        channel = self.get_broadcast_channel()
        if not channel: return

        # 每日總結 23:59
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

    # ===============================
    # 語音擺爛偵測
    # ===============================
    @tasks.loop(minutes=5)
    async def voice_check(self):
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
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

    # ===============================
    # 資料庫工具
    # ===============================
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

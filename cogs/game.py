import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta, timezone
import random
import os
import google.generativeai as genai

class KobeBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "kobe_bot.db"
        self.active_game_sessions = {}  # {user_id: start_time}
        self.game_times = {}  # {user_id: total_seconds_today}
        self.cooldowns = {}  # AI 回應冷卻
        self.last_message_time = {}  # 防止 spam

        # AI 初始化
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                print("✅ Gemini 2.0 AI 啟動成功")
            except Exception as e:
                print(f"❌ AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS daily_stats (
                    user_id INTEGER PRIMARY KEY,
                    msg_count INTEGER DEFAULT 0,
                    lazy_points INTEGER DEFAULT 0,
                    game_seconds INTEGER DEFAULT 0,
                    last_updated DATE
                )
            ''')
            await db.commit()
        self.game_check.start()
        self.daily_tasks.start()
        self.random_mood.start()

    async def cog_unload(self):
        self.game_check.cancel()
        self.daily_tasks.cancel()
        self.random_mood.cancel()

    # ==========================================
    # AI 核心：Kobe 毒舌
    # ==========================================
    async def ask_kobe(self, prompt, max_tokens=60):
        if not self.has_ai: return None
        sys_prompt = (
            "你是 Kobe Bryant，語氣毒舌、嚴格、耿直、痛恨 NBA2K，不恭維。"
            "用繁體中文回答，50字內，有趣又耿，不要敬語。"
        )
        try:
            response = await asyncio.to_thread(
                self.model.generate_content,
                contents=[sys_prompt, prompt]
            )
            return response.text
        except:
            return None

    # ==========================================
    # 每日任務、排行榜
    # ==========================================
    @tasks.loop(minutes=1)
    async def daily_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        channel = self.get_broadcast_channel()
        if not channel: return

        # 晨間挑戰
        if now.hour == 6 and now.minute == 0:
            challenges = ["閱讀 30 分鐘", "伏地挺身 50 下", "不喝含糖飲料", "背 10 個英文單字", "整理房間"]
            task = random.choice(challenges)
            await channel.send(f"☀️ **曼巴每日挑戰**：{task}，完成後榮譽 +10！")

        # 每日結算
        if now.hour == 23 and now.minute == 59:
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute("SELECT user_id, lazy_points, game_seconds FROM daily_stats ORDER BY lazy_points DESC LIMIT 3")
                top = await cursor.fetchall()
                if not top: return
                text = "📊 **今日廢物榜**\n"
                for idx, row in enumerate(top, start=1):
                    text += f"{idx}️⃣ <@{row[0]}> | 懶惰指數 {row[1]} | 遊戲時間 {row[2]//60} 分鐘\n"
                await channel.send(text)
                # 清空每日統計
                await db.execute("DELETE FROM daily_stats")
                await db.commit()

    # ==========================================
    # 遊戲時間偵測與毒舌
    # ==========================================
    @tasks.loop(minutes=1)
    async def game_check(self):
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot: continue
                game = next((a.name for a in member.activities if a.type == discord.ActivityType.playing), None)
                if game:
                    now = time.time()
                    user_id = member.id
                    start = self.active_game_sessions.get(user_id, now)
                    self.active_game_sessions[user_id] = start
                    played_seconds = now - start + self.game_times.get(user_id, 0)
                    self.game_times[user_id] = played_seconds
                    # 超過 1 小時
                    if played_seconds >= 3600 and (user_id not in self.cooldowns or now - self.cooldowns[user_id] > 1800):
                        channel = self.get_text_channel(guild)
                        if channel:
                            msg = f"🏀🐍 {member.mention} 玩那麼久？你的眼神還亮嗎？"
                            await channel.send(msg)
                            await self.update_stat(user_id, "lazy_points", 5)
                            self.cooldowns[user_id] = now

    # ==========================================
    # 聊天訊息監控
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        user_id = message.author.id
        now = time.time()
        # 防止重複 spam
        if user_id in self.last_message_time and now - self.last_message_time[user_id] < 15:
            return
        self.last_message_time[user_id] = now

        # 更新每日訊息量
        await self.update_stat(user_id, "msg_count", 1)

        # 如果訊息以 ? 結尾，AI Kobe 回應
        if message.content.strip().endswith("?") and self.has_ai:
            reply = await self.ask_kobe(f"用戶問：{message.content}")
            if reply:
                await message.reply(reply[:200])

    # ==========================================
    # 隨機心情毒舌
    # ==========================================
    @tasks.loop(minutes=60)
    async def random_mood(self):
        channel = self.get_broadcast_channel()
        if not channel: return
        messages = [
            "🏀🐍 休息太久？先去訓練，眼神才亮",
            "🏀🐍 再玩下去？你的眼神還亮嗎",
            "🏀🐍 打開書本，別只會按表情"
        ]
        await channel.send(random.choice(messages))

    # ==========================================
    # 資料庫工具
    # ==========================================
    async def update_stat(self, user_id, column, value):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM daily_stats WHERE user_id = ?", (user_id,))
            if not await cursor.fetchone():
                await db.execute("INSERT INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
            await db.execute(f"UPDATE daily_stats SET {column} = {column} + ? WHERE user_id = ?", (value, user_id))
            await db.commit()

    def get_broadcast_channel(self):
        if not self.bot.guilds: return None
        guild = self.bot.guilds[0]
        return self.get_text_channel(guild)

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target), guild.text_channels) or guild.text_channels[0]

async def setup(bot):
    await bot.add_cog(KobeBot(bot))

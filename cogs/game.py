import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta, timezone
import random
import os
import google.generativeai as genai
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        # 結構: {user_id: {"game": "LoL", "start": timestamp, "1h_warned": False, "2h_warned": False}}
        self.active_sessions = {} 
        self.cooldowns = {}
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        
        # --- AI 設定 (Gemini 2.0 Flash) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                logger.info("✅ Gemini 2.0 Flash 啟動成功 (教練模式)")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
                self.has_ai = False
        else:
            self.has_ai = False

        self.kobe_quotes = ["Mamba Out. 🎤", "別吵我，正在訓練。🏀", "那些殺不死你的，只會讓你更強。🐍", "Soft. 🥚"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            # 建立 playtime 表 (注意：主鍵是 user_id + game_name)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS playtime (
                    user_id INTEGER, 
                    game_name TEXT, 
                    seconds INTEGER DEFAULT 0, 
                    last_played DATE, 
                    PRIMARY KEY(user_id, game_name)
                )
            ''')
            # 建立其他表
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE)')
            await db.commit()
        
        # 啟動任務
        self.daily_tasks.start()
        self.game_check.start()
        
        # 🔥 關鍵功能：啟動時掃描所有正在玩遊戲的人 (不用等切換)
        # 等待 bot 緩存準備好
        await self.bot.wait_until_ready()
        print("🔍 正在掃描現有遊戲狀態...")
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot: continue
                # 檢查是否有在玩遊戲
                game = next((a.name for a in member.activities if a.type == discord.ActivityType.playing), None)
                if game and member.id not in self.active_sessions:
                    # 補登入 active_sessions
                    self.active_sessions[member.id] = {
                        "game": game, 
                        "start": time.time(), # 從現在開始算 (雖然不完美，但比沒算好)
                        "1h_warned": False,
                        "2h_warned": False
                    }
                    print(f"   -> 偵測到 {member.display_name} 正在玩 {game}，已開始計時。")

    async def cog_unload(self):
        self.daily_tasks.cancel()
        self.game_check.cancel()

    # ==========================================
    # 🧠 AI 核心：教練模式 (回答問題 + 罵人)
    # ==========================================
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30):
        if not self.has_ai: return None

        now = time.time()
        if user_id and cooldown_dict:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time: return "COOLDOWN"
            cooldown_dict[user_id] = now

        try:
            sys_prompt = (
                "你是 Kobe Bryant。個性：嚴格、專業、痛恨懶惰，但作為教練，你必須給出實質指導。\n"
                "1. **若用戶問問題 (知識/技術)**：先專業簡短回答，再嚴厲督促。\n"
                "2. **若用戶在偷懶/玩遊戲**：狠狠罵他浪費生命。\n"
                "3. **若提到 NBA 2K**：暴怒，那是電子垃圾。\n"
                "4. 繁體中文(台灣)，50字內，多用 emoji (🏀🐍)。"
            )
            response = await asyncio.to_thread(self.model.generate_content, contents=[sys_prompt, f"用戶：{prompt}"])
            return response.text
        except: return None

    # ==========================================
    # 📊 排行榜指令 (!rank / !r)
    # ==========================================
    @commands.command(aliases=['r'])
    async def rank(self, ctx):
        """查看遊戲時長排行榜 (含正在進行的時間)"""
        async with aiosqlite.connect(self.db_name) as db:
            # 1. 先抓資料庫裡的總時數
            cursor = await db.execute('SELECT user_id, SUM(seconds) as total FROM playtime GROUP BY user_id')
            rows = await cursor.fetchall()
            
        # 轉換成字典 {user_id: total_seconds}
        stats = {row[0]: row[1] for row in rows}
        
        # 2. 🔥 加上「正在玩」的時間 (Real-time)
        now = time.time()
        for uid, session in self.active_sessions.items():
            current_duration = int(now - session['start'])
            stats[uid] = stats.get(uid, 0) + current_duration

        # 3. 排序 (由大到小)
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

        if not sorted_stats:
            return await ctx.send("📊 目前沒有遊戲紀錄！大家都很認真訓練？(還是 bot 剛醒？)")

        # 4. 顯示
        embed = discord.Embed(title="🏆 偷懶排行榜 (遊戲時長)", color=0xffd700)
        description = ""
        
        for i, (uid, seconds) in enumerate(sorted_stats):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"用戶({uid})"
            
            # 格式化時間
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            
            # 狀態圖示
            status_icon = "🎮 正在玩" if uid in self.active_sessions else "💤"
            
            description += f"**{i+1}. {name}**\n   └ {hours}小時 {mins}分 {status_icon}\n"

        embed.description = description
        embed.set_footer(text="統計包含歷史紀錄 + 正在進行的遊戲")
        await ctx.send(embed=embed)

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
        # 簡單防抖動
        if user_id in self.cooldowns and now - self.cooldowns.get(user_id, 0) < 2: return
        self.cooldowns[user_id] = now 

        # A. 遊戲開始
        if new_game and not old_game:
            self.active_sessions[user_id] = {
                "game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False
            }
            
            # AI 罵人
            prompt = f"這軟蛋開始玩 {new_game} 了。" + ("痛罵他玩2K是垃圾" if "2k" in new_game.lower() else "罵他不去訓練")
            roast = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            if not roast or roast == "COOLDOWN":
                roast = f"{after.mention} 玩 **{new_game}**？不用唸書嗎？😡"
            
            if channel: await channel.send(roast)

        # B. 遊戲結束
        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                duration = int(time.time() - session["start"])
                
                # 🔥 存檔 (累加模式)
                await self.save_to_db(user_id, old_game, duration)
                del self.active_sessions[user_id]
                
                # 採訪
                if duration > 600 and channel:
                    mins = duration // 60
                    prompt = f"{after.display_name} 玩了 {mins} 分鐘 {old_game}。質問他學到了什麼？"
                    interview = await self.ask_kobe(prompt, user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN": 
                        await channel.send(f"🎤 **賽後毒舌採訪** {after.mention}\n{interview}")

    # ==========================================
    # 💾 資料庫存檔 (修正為累加)
    # ==========================================
    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 10: return # 太短不記
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            # 使用 UPSERT 語法 (SQLite 3.24+)：如果存在就加秒數，不存在就插入
            await db.execute('''
                INSERT INTO playtime (user_id, game_name, seconds, last_played) 
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, game_name) 
                DO UPDATE SET seconds = seconds + excluded.seconds, last_played = excluded.last_played
            ''', (user_id, game_name, seconds, today))
            await db.commit()

    # ==========================================
    # ⏰ 時間監控 (超時警告)
    # ==========================================
    @tasks.loop(minutes=1)
    async def game_check(self):
        now = time.time()
        for user_id, session in list(self.active_sessions.items()):
            duration = int(now - session["start"])
            
            # 1小時警告
            if duration >= 3600 and not session.get("1h_warned"):
                session["1h_warned"] = True
                await self.send_warning(user_id, session["game"], "1小時", 5)
            
            # 2小時警告
            if duration >= 7200 and not session.get("2h_warned"):
                session["2h_warned"] = True
                await self.send_warning(user_id, session["game"], "2小時", 10)

    async def send_warning(self, user_id, game, time_str, penalty):
        # 簡易發送邏輯
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild:
            member = guild.get_member(user_id)
            channel = self.get_text_channel(guild)
            if member and channel:
                msg = await self.ask_kobe(f"用戶玩 {game} 超過 {time_str}，罵他眼睛瞎了嗎") or f"{member.mention} {time_str}了！眼睛不乾嗎？"
                await channel.send(f"⚠️ **{time_str} 警報** {member.mention}\n{msg}")
                # 這裡假設有 lazy_points 欄位在 daily_stats
                async with aiosqlite.connect(self.db_name) as db:
                     await db.execute("UPDATE daily_stats SET lazy_points = lazy_points + ? WHERE user_id = ?", (penalty, user_id))
                     await db.commit()

    # ==========================================
    # 💬 聊天監控 (AI 回話)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # 優先處理指令
        if message.content.startswith('!'):
            # 這裡不呼叫 process_commands，因為 main.py 會處理
            return 

        is_mentioned = self.bot.user in message.mentions or message.content.strip().endswith("?")
        if is_mentioned:
            async with message.channel.typing():
                reply = await self.ask_kobe(message.content, message.author.id, self.ai_chat_cooldowns, 5)
                await message.reply(reply or random.choice(self.kobe_quotes))
            return

    # Helper
    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target) and x.permissions_for(guild.me).send_messages, guild.text_channels) or guild.text_channels[0]

    @tasks.loop(hours=24)
    async def daily_tasks(self):
        pass 

async def setup(bot):
    await bot.add_cog(Game(bot))

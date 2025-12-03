import discord
from discord.ext import commands
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta
import random
import os
import google.generativeai as genai

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        self.active_sessions = {}
        self.focus_sessions = {}
        
        # --- 冷卻系統 (API 省流關鍵) ---
        self.chat_cooldowns = {}      # 藉口粉碎機冷卻 (被動監聽)
        self.ai_roast_cooldowns = {}  # 遊戲罵人 AI 冷卻
        self.ai_chat_cooldowns = {}   # 對話 AI 冷卻
        
        # --- 1. 設定 Google Gemini AI ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            # 使用 Flash 模型 (速度快、省額度)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            self.has_ai = True
            print("✅ AI 模組已啟動 (Gemini 1.5 Flash)")
        else:
            print("⚠️ 警告：找不到 GEMINI_API_KEY，將使用備用模式。")
            self.has_ai = False

        # --- 備用語錄 (當 AI 掛掉時用) ---
        self.default_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？",
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS streaks (user_id INTEGER PRIMARY KEY, current_streak INTEGER DEFAULT 0, last_checkin_date DATE)')
            await db.commit()

    # ==========================================
    # 🧠 AI 核心：呼叫柯比 (含冷卻機制)
    # ==========================================
    async def ask_kobe(self, prompt, user_id, cooldown_dict, cooldown_time=30):
        if not self.has_ai: return None

        # 檢查冷卻
        now = time.time()
        if user_id in cooldown_dict:
            if now - cooldown_dict[user_id] < cooldown_time:
                return None 
        
        cooldown_dict[user_id] = now # 更新冷卻

        try:
            # 柯比人設
            system_prompt = (
                "你現在是 Kobe Bryant (黑曼巴)。"
                "個性：極度好勝、毒舌、痛恨軟弱、看不起找藉口的人。"
                "口頭禪：Soft, Mamba Out, What can I say。"
                "請用「繁體中文 (台灣)」回答。"
                "回答要簡短有力 (50字內)，盡量兇，多用 emoji (🏀🐍💀🔥)。"
                f"情況：{prompt}"
            )
            response = await asyncio.to_thread(self.model.generate_content, system_prompt)
            return response.text
        except:
            return None

    # ==========================================
    # 🎯 遊戲監控 (含賽後採訪)
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)
        channel = self.get_text_channel(after.guild)

        if new_game == old_game: return

        # A. 專注模式偷玩 (重罰)
        if user_id in self.focus_sessions and new_game:
            task = self.focus_sessions.pop(user_id)
            task.cancel()
            await self.add_honor(user_id, -50)
            if channel:
                await channel.send(f"🚨 **抓到了！騙子！**\n{after.mention} 專注時偷玩 **{new_game}**！榮譽 -50！😡")
                if after.voice: await after.voice.disconnect()
            return

        # B. 🎤 賽後毒舌記者會 (遊戲結束時觸發)
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]
                    
                    # 只有玩超過 10 分鐘才採訪，避免洗版
                    if duration > 600 and channel:
                        mins = duration // 60
                        prompt = f"{after.display_name} 剛玩了 {mins} 分鐘的 {old_game}。請像記者一樣質問他：這段時間學到了什麼？是不是在浪費生命？還是有進步？"
                        interview_msg = await self.ask_kobe(prompt, user_id, self.ai_chat_cooldowns, cooldown_time=0) # 這裡不設冷卻，保證觸發
                        if interview_msg:
                            await channel.send(f"🎤 **賽後毒舌採訪** {after.mention}\n{interview_msg}")

        # C. 遊戲開始 (AI 罵人 + 語音突襲)
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # AI 生成罵人 (冷卻 5 分鐘)
            roast_msg = await self.ask_kobe(f"這個軟蛋開始玩 {new_game} 了，罵他為什麼不去訓練。", user_id, self.ai_roast_cooldowns, cooldown_time=300)
            
            # 如果 AI 冷卻或失敗，用備用
            if not roast_msg:
                roast_msg = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
            else:
                roast_msg = f"{after.mention} {roast_msg}"

            # 語音突襲
            if after.voice and after.voice.channel:
                try:
                    vc = after.guild.voice_client
                    if not vc: await after.voice.channel.connect()
                    elif vc.channel != after.voice.channel: await vc.move_to(after.voice.channel)
                    if channel:
                        await channel.send(f"🎙️ **語音查哨！**\n{roast_msg}")
                except: pass
            else:
                if channel: await channel.send(roast_msg)

    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        c = discord.utils.find(lambda x: any(t in x.name.lower() for t in target) and x.permissions_for(guild.me).send_messages, guild.text_channels)
        return c or discord.utils.find(lambda x: x.permissions_for(guild.me).send_messages, guild.text_channels)

    # ==========================================
    # 💬 聊天監控 (藉口粉碎機 + AI 對話)
    # ==========================================
    async def add_honor(self, user_id, amount):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (user_id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.content.startswith("!"): return
        user_id = message.author.id
        content = message.content

        # --- 1. AI 對話 (被標記/回覆時觸發) ---
        if self.bot.user in message.mentions or (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user):
            async with message.channel.typing():
                # 冷卻 5 秒，可以像聊天一樣對話
                reply = await self.ask_kobe(f"用戶對你說：{content}", user_id, self.ai_chat_cooldowns, cooldown_time=5)
                if reply:
                    await message.reply(reply)
                else:
                    await message.reply("別吵我，正在訓練。🏀 (冷卻中)")
            return 

        # --- 2. 🧠 智能藉口粉碎機 (被動監聽) ---
        # 為了省額度，我們設定每人每 60 秒只能觸發一次「被動分析」
        now = time.time()
        if user_id in self.chat_cooldowns:
            if now - self.chat_cooldowns[user_id] < 60: return 

        if self.has_ai:
            try:
                # 讓 AI 判斷這句話是軟弱還是強硬
                prompt = (
                    f"分析這句話：『{content}』\n"
                    "如果是找藉口、偷懶、軟弱、想放棄，回答 'WEAK'。"
                    "如果是努力、堅持、訓練、拼搏，回答 'STRONG'。"
                    "如果是普通聊天，回答 'NORMAL'。"
                    "只回答一個單字。"
                )
                response = await asyncio.to_thread(self.model.generate_content, prompt)
                result = response.text.strip().upper()
                
                change = 0
                comment_prompt = ""

                if "WEAK" in result:
                    change = -5
                    comment_prompt = f"使用者說『{content}』，他在找藉口。用 Kobe 語氣罵醒他。"
                elif "STRONG" in result:
                    change = 5
                    comment_prompt = f"使用者說『{content}』，很有曼巴精神。用 Kobe 語氣肯定他。"

                if change != 0:
                    self.chat_cooldowns[user_id] = now
                    await self.add_honor(user_id, change)
                    
                    # 生成評語
                    comment = await self.ask_kobe(comment_prompt, user_id, {}, cooldown_time=0) # 這裡不需額外冷卻
                    
                    color = 0x2ecc71 if change > 0 else 0xe74c3c
                    embed = discord.Embed(description=f"{message.author.mention} {comment}\n(AI 判定榮譽值: `{change:+d}`)", color=color)
                    await message.channel.send(embed=embed)

            except: pass

    # ==========================================
    # 📜 其他指令 (維持不變)
    # ==========================================
    @commands.command()
    async def focus(self, ctx, minutes: int):
        if minutes < 1 or minutes > 180: return await ctx.send("❌ 時間限 1~180 分鐘！")
        if ctx.author.id in self.focus_sessions: return await ctx.send("⚠️ 已經在專注模式中了！")
        await ctx.send(f"🔒 **專注啟動！** `{minutes}` 分鐘。\n偷玩遊戲 = **榮譽 -50 + 踢出語音**！")
        self.focus_sessions[ctx.author.id] = asyncio.create_task(self.focus_timer(ctx, minutes))

    async def focus_timer(self, ctx, minutes):
        try:
            await asyncio.sleep(minutes * 60)
            if ctx.author.id in self.focus_sessions:
                bonus = minutes // 2
                await self.add_honor(ctx.author.id, bonus)
                await ctx.send(f"✅ **修煉完成！** {ctx.author.mention} 堅持了 `{minutes}` 分鐘！榮譽 `+{bonus}`！")
                del self.focus_sessions[ctx.author.id]
        except asyncio.CancelledError: pass

    @commands.command(aliases=["ci"])
    async def checkin(self, ctx):
        user_id, today = ctx.author.id, datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            row = await (await db.execute("SELECT current_streak, last_checkin_date FROM streaks WHERE user_id = ?", (user_id,))).fetchone()
            streak, last = (row[0], row[1]) if row else (0, None)
            if last == today: return await ctx.send(f"⏳ 今天打過卡了！連勝：`{streak}` 天。")
            new_streak = streak + 1 if last == yesterday else 1
            reward = min(new_streak * 2, 20)
            await db.execute("INSERT OR REPLACE INTO streaks (user_id, current_streak, last_checkin_date) VALUES (?, ?, ?)", (user_id, new_streak, today))
            await db.commit()
            await self.add_honor(user_id, reward)
            msg = "🔥 **連勝延續！**" if last == yesterday else "📝 **重新開始！**"
            await ctx.send(f"{msg}\n{ctx.author.mention} 打卡成功 (第 `{new_streak}` 天)！榮譽 `+{reward}`！")

    @commands.command()
    async def honor(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        async with aiosqlite.connect(self.db_name) as db:
            row = await (await db.execute("SELECT points FROM honor WHERE user_id = ?", (target.id,))).fetchone()
            points = row[0] if row else 0
        title, color = self.get_title(points)
        embed = discord.Embed(title=f"📜 {target.display_name} 的榮譽", color=color)
        embed.add_field(name="稱號", value=f"**{title}**", inline=False)
        embed.add_field(name="點數", value=f"`{points}`", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command()
    async def rank(self, ctx):
        async with aiosqlite.connect(self.db_name) as db:
            rows = await (await db.execute('SELECT user_id, SUM(seconds) as total FROM playtime GROUP BY user_id')).fetchall()
            stats = {row[0]: row[1] for row in rows}
            now = time.time()
            for uid, s in self.active_sessions.items(): stats[uid] = stats.get(uid, 0) + int(now - s['start'])
            sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
            if not sorted_stats: return await ctx.send("📊 沒人玩遊戲！")
            text = ""
            for i, (uid, sec) in enumerate(sorted_stats):
                m = ctx.guild.get_member(uid)
                name = m.display_name if m else f"用戶({uid})"
                status = "🎮" if uid in self.active_sessions else ""
                text += f"{i+1}. **{name}** {status}: {sec//3600}小時 {(sec%3600)//60}分\n"
            embed = discord.Embed(title="🏆 遊戲時長排行榜", description=text, color=0xffd700)
            await ctx.send(embed=embed)

    @commands.command()
    async def leaderboard(self, ctx):
        async with aiosqlite.connect(self.db_name) as db:
            rows = await (await db.execute("SELECT user_id, points FROM honor ORDER BY points DESC LIMIT 10")).fetchall()
        if not rows: return await ctx.send("📊 榮譽榜是空的！")
        text = ""
        for i, (uid, pts) in enumerate(rows):
            m = ctx.guild.get_member(uid)
            name = m.display_name if m else f"用戶({uid})"
            title, _ = self.get_title(pts)
            text += f"{i+1}. **{name}** (`{pts}`) - {title}\n"
        embed = discord.Embed(title="🏆 曼巴榮譽排行榜", description=text, color=0x9b59b6)
        await ctx.send(embed=embed)

    @commands.command()
    async def respect(self, ctx, target: discord.Member):
        if target == ctx.author: return await ctx.send("❌ 不能投自己！")
        await self.vote(ctx, target, 10, "🫡 致敬")

    @commands.command()
    async def blame(self, ctx, target: discord.Member):
        if target == ctx.author: return await ctx.send("❌ 不能投自己！")
        await self.vote(ctx, target, -10, "👎 譴責")

    async def vote(self, ctx, target, amount, action):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            row = await (await db.execute("SELECT last_vote_date FROM honor WHERE user_id = ?", (ctx.author.id,))).fetchone()
            if row and row[0] == today: return await ctx.send("⏳ 今天投過了！")
            await db.execute("INSERT OR REPLACE INTO honor (user_id, points, last_vote_date) VALUES (?, (SELECT points FROM honor WHERE user_id=?), ?)", (ctx.author.id, ctx.author.id, today))
            await self.add_honor(target.id, amount)
            await db.commit()
        await ctx.send(f"{ctx.author.mention} {action} {target.mention}！ (榮譽 `{amount:+d}`)")

    def get_title(self, points):
        if points >= 500: return "🐍 黑曼巴", 0xf1c40f
        if points >= 300: return "⭐ 全明星", 0x3498db
        if points >= 100: return "🏀 先發", 0x2ecc71
        if points >= 0: return "🪑 替補", 0xe67e22
        return "🤡 飲水機", 0xe74c3c

async def setup(bot):
    await bot.add_cog(Game(bot))

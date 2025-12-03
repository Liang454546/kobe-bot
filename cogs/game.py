import discord
from discord.ext import commands
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta
import random
import os
import google.generativeai as genai # 引入 AI 模組

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        self.active_sessions = {}
        self.focus_sessions = {}
        self.chat_cooldowns = {}
        self.roast_cooldowns = {} # 避免 AI 短時間被呼叫太多次

        # --- 設定 AI ---
        # 嘗試從環境變數讀取 API KEY
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-pro')
            self.has_ai = True
        else:
            print("⚠️ 警告：找不到 GEMINI_API_KEY，將使用備用預設語錄。")
            self.has_ai = False

        # --- 備用罵人語錄 (當 AI 掛掉或沒設定時用) ---
        self.backup_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？",
            "嗶嗶！裁判！{member} 在玩 **{game}** 犯規！"
        ]
        
        # --- 榮譽系統語錄 ---
        self.weak_words = ["累", "好累", "想睡", "放棄", "好難", "不想動", "休息", "明天再說", "擺爛"]
        self.strong_words = ["健身", "訓練", "加班", "寫扣", "唸書", "拼了", "努力", "堅持", "搞定", "練球"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS streaks (user_id INTEGER PRIMARY KEY, current_streak INTEGER DEFAULT 0, last_checkin_date DATE)')
            await db.commit()

    # --- 🔥 核心：呼叫 AI 生成罵人話 ---
    async def generate_roast(self, member_name, game_name):
        if not self.has_ai:
            return random.choice(self.backup_roasts).format(member=member_name, game=game_name)

        try:
            # 設定 AI 的人設 (Prompt)
            prompt = (
                f"你現在是 NBA 傳奇球星 Kobe Bryant (黑曼巴)。"
                f"你的隊友 {member_name} 正在偷懶玩遊戲「{game_name}」，而不是去訓練或努力。"
                f"請用非常嚴厲、恨鐵不成鋼、帶有「曼巴精神」風格的語氣罵他。"
                f"字數限制 50 字以內，要兇，可以使用 emoji。"
                f"直接給我罵人的內容，不要有引號或其他廢話。"
            )
            
            # 呼叫 AI (跑在背景執行緒以免卡住機器人)
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return f"{member_name} {response.text}"
        except Exception as e:
            print(f"AI 生成失敗: {e}")
            return random.choice(self.backup_roasts).format(member=member_name, game=game_name)

    # ==========================================
    # 🎯 監控邏輯 (整合 AI)
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game == old_game: return

        # A. 專注模式偷玩
        if user_id in self.focus_sessions and new_game:
            task = self.focus_sessions.pop(user_id)
            task.cancel()
            await self.add_honor(user_id, -50)
            
            channel = self.get_text_channel(after.guild)
            if channel:
                # 這裡也可以用 AI 罵，但為了即時性先用固定的
                await channel.send(f"🚨 **抓到了！騙子！**\n{after.mention} 說要專注，結果偷開 **{new_game}**！\n**榮譽值重扣 50 分！** 😡👎")
                if after.voice: await after.voice.disconnect()
            return

        # B. 遊戲結束存檔
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]

        # C. 遊戲開始 -> AI 罵人
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            channel = self.get_text_channel(after.guild)
            
            # 生成罵人內容 (若是短時間重複觸發，可能需要冷卻，這裡簡單處理)
            roast_msg = await self.generate_roast(after.mention, new_game)

            # 語音突襲
            if after.voice and after.voice.channel:
                try:
                    vc = after.guild.voice_client
                    if not vc: await after.voice.channel.connect()
                    elif vc.channel != after.voice.channel: await vc.move_to(after.voice.channel)
                    
                    if channel:
                        # 語音 TTS 廣播
                        await channel.send(f"🎙️ **語音查哨！** {after.display_name} 在玩 {new_game}！")
                        # 貼上 AI 產生的罵人文字
                        await channel.send(roast_msg)
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

    # ... (以下保留 focus, checkin, honor, rank, leaderboard, respect, blame 指令，與上一版完全相同，不需更動) ...
    # 為了節省篇幅，請將上一篇的後半段指令區直接貼在這裡即可
    # 如果您需要完整的，請告訴我，我再一次貼全部給您
    
    # ==========================================
    # 🔥 專注模式 (!focus)
    # ==========================================
    @commands.command()
    async def focus(self, ctx, minutes: int):
        if minutes < 1 or minutes > 180: return await ctx.send("❌ 時間限 1~180 分鐘！")
        if ctx.author.id in self.focus_sessions: return await ctx.send("⚠️ 你已經在專注模式中了！")

        await ctx.send(f"🔒 **專注啟動！**\n{ctx.author.mention} 設定 `{minutes}` 分鐘。\n**警告：偷玩遊戲 = 榮譽 -50 + 踢出語音！**")
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

    # ==========================================
    # 📅 每日簽到 (!checkin)
    # ==========================================
    @commands.command(aliases=["ci"])
    async def checkin(self, ctx):
        user_id, today = ctx.author.id, datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT current_streak, last_checkin_date FROM streaks WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            streak, last = (row[0], row[1]) if row else (0, None)

            if last == today: return await ctx.send(f"⏳ 今天打過卡了！連勝：`{streak}` 天。")
            
            new_streak = streak + 1 if last == yesterday else 1
            reward = min(new_streak * 2, 20)
            
            await db.execute("INSERT OR REPLACE INTO streaks (user_id, current_streak, last_checkin_date) VALUES (?, ?, ?)", (user_id, new_streak, today))
            await db.commit()
            
            await self.add_honor(user_id, reward)
            msg = "🔥 **連勝延續！**" if last == yesterday else "📝 **重新開始！**"
            await ctx.send(f"{msg}\n{ctx.author.mention} 打卡成功 (第 `{new_streak}` 天)！榮譽 `+{reward}`！")

    # ==========================================
    # 💬 聊天與榮譽 (含防刷分冷卻)
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
        now = time.time()
        if user_id in self.chat_cooldowns:
            if now - self.chat_cooldowns[user_id] < 60: return 

        content = message.content.lower()
        change, response = 0, ""

        if any(w in content for w in self.weak_words):
            change, response = -2, "累了？永遠是替補！😤" # 簡化回應，AI 用在遊戲偵測就好
        elif any(w in content for w in self.strong_words):
            change, response = 2, "沒錯！曼巴精神！🏀🔥"

        if change:
            self.chat_cooldowns[user_id] = now
            await self.add_honor(user_id, change)
            color = 0x2ecc71 if change > 0 else 0xe74c3c
            await message.channel.send(embed=discord.Embed(description=f"{message.author.mention} {response}", color=color))

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
            for uid, s in self.active_sessions.items():
                stats[uid] = stats.get(uid, 0) + int(now - s['start'])
            
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

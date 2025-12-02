import discord
from discord.ext import commands
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta
import random

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        self.active_sessions = {} # 記錄正在玩遊戲的人 (計時用)
        self.focus_sessions = {}  # 記錄正在專注的人 (監控用)
        self.chat_cooldowns = {}  # 🔥 新增：聊天獎勵冷卻 {user_id: timestamp}
        
        # --- 1. 遊戲罵人語錄 ---
        self.targeted_roasts = {
            "gta": "俠盜獵車手？🚗 這裡不是洛聖都，去努力工作吧！",
            "nba": "玩 NBA 2K？🏀 手指動得比腳快有什麼用？去球場流汗！",
            "league of legends": "又在打 LOL？💀 你的心態炸裂了嗎？",
            "valorant": "特戰英豪？槍法再準，現實生活打不中目標有什麼用？",
            "apex": "APEX？你的肝還好嗎？別再當滋崩狗了！",
            "原神": "啟動？😱 給我把書桌前的燈啟動！"
        }
        self.default_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？",
            "嗶嗶！裁判！{member} 在玩 **{game}** 犯規！"
        ]

        # --- 2. 榮譽系統語錄 ---
        self.weak_words = ["累", "好累", "想睡", "放棄", "好難", "不想動", "休息", "明天再說", "擺爛"]
        self.weak_roasts = ["累了？永遠是替補！😤", "想休息？對手在訓練！📉", "軟弱！曼巴精神不允許！🚫"]
        self.strong_words = ["健身", "訓練", "加班", "寫扣", "唸書", "拼了", "努力", "堅持", "搞定", "練球"]
        self.strong_encourage = ["沒錯！曼巴精神！🏀🔥", "保持專注！通往偉大！✨", "我看見你的努力了！💪"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS streaks (user_id INTEGER PRIMARY KEY, current_streak INTEGER DEFAULT 0, last_checkin_date DATE)')
            await db.commit()

    # ==========================================
    # 🎯 核心監控邏輯 (專注 + 遊戲罵人 + 紀錄)
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game == old_game: return

        # A. 專注模式偷玩懲罰
        if user_id in self.focus_sessions and new_game:
            task = self.focus_sessions.pop(user_id)
            task.cancel()
            await self.add_honor(user_id, -50)
            
            channel = self.get_text_channel(after.guild)
            if channel:
                await channel.send(f"🚨 **抓到了！騙子！**\n{after.mention} 說要專注，結果偷偷打開了 **{new_game}**！\n**修煉失敗！榮譽值重扣 50 分！** 😡👎")
                if after.voice:
                    await after.voice.disconnect()
                    await channel.send("👻 (並且被踢出了語音頻道)")
            return

        # B. 遊戲結束存檔
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]

        # C. 遊戲開始罵人
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            game_lower = new_game.lower()
            roast_msg = next((text for kw, text in self.targeted_roasts.items() if kw in game_lower), None)
            if not roast_msg:
                roast_msg = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
            else:
                roast_msg = f"{after.mention} {roast_msg}"

            channel = self.get_text_channel(after.guild)
            
            if after.voice and after.voice.channel:
                try:
                    vc = after.guild.voice_client
                    if not vc: await after.voice.channel.connect()
                    elif vc.channel != after.voice.channel: await vc.move_to(after.voice.channel)
                    
                    if channel:
                        tts = f"喂！{after.display_name}！我抓到你在偷玩 {new_game}！專心一點！"
                        await channel.send(tts, tts=True)
                        await channel.send(f"🎙️ **語音查哨突襲！**\n{roast_msg}")
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
        
        # 1. 檢查是否在冷卻中
        user_id = message.author.id
        now = time.time()
        if user_id in self.chat_cooldowns:
            # 冷卻時間 60 秒
            if now - self.chat_cooldowns[user_id] < 60:
                return 

        content = message.content.lower()
        change, response = 0, ""

        if any(w in content for w in self.weak_words):
            change, response = -2, random.choice(self.weak_roasts)
        elif any(w in content for w in self.strong_words):
            change, response = 2, random.choice(self.strong_encourage)

        if change:
            # 觸發成功，更新冷卻時間
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

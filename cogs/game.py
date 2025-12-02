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
        self.focus_sessions = {} # 格式: {user_id: task_object} 用來追蹤誰正在專注
        
        # --- 聊天室榮譽關鍵字 ---
        self.weak_words = ["累", "好累", "想睡", "放棄", "好難", "不想動", "休息", "明天再說", "擺爛"]
        self.weak_roasts = [
            "累了？這就是為什麼你永遠是替補！😤 (榮譽 -2)",
            "想休息？你的對手正在訓練呢！📉 (榮譽 -2)",
            "軟弱！曼巴精神不允許你說這句話！🚫 (榮譽 -2)"
        ]
        self.strong_words = ["健身", "訓練", "加班", "寫扣", "唸書", "拼了", "努力", "堅持", "搞定", "練球"]
        self.strong_encourage = [
            "沒錯！這就是曼巴精神！🏀🔥 (榮譽 +2)",
            "保持專注！你正在通往偉大的路上！✨ (榮譽 +2)",
            "我看見你的努力了！繼續保持！💪 (榮譽 +2)"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            # 1. 榮譽表
            await db.execute('''
                CREATE TABLE IF NOT EXISTS honor (
                    user_id INTEGER PRIMARY KEY, 
                    points INTEGER DEFAULT 0,
                    last_vote_date DATE
                )
            ''')
            # 2. 簽到表
            await db.execute('''
                CREATE TABLE IF NOT EXISTS streaks (
                    user_id INTEGER PRIMARY KEY, 
                    current_streak INTEGER DEFAULT 0,
                    last_checkin_date DATE
                )
            ''')
            await db.commit()

    # ==========================================
    # 🔥 A. 專注模式邏輯 (Focus Mode)
    # ==========================================
    @commands.command()
    async def focus(self, ctx, minutes: int):
        """開啟專注模式，期間玩遊戲會被重罰"""
        if minutes < 1 or minutes > 180:
            return await ctx.send("❌ 時間請設定在 1 ~ 180 分鐘之間！")
        
        if ctx.author.id in self.focus_sessions:
            return await ctx.send("⚠️ 你已經在專注模式中了！別分心！")

        # 發送確認
        await ctx.send(f"🔒 **專注模式啟動！**\n{ctx.author.mention} 設定了 `{minutes}` 分鐘的修煉時間。\n**警告：如果這期間你開啟任何遊戲，榮譽值將直接 -50 並被公開羞辱！**")
        
        # 建立背景倒數任務
        task = asyncio.create_task(self.focus_timer(ctx, minutes))
        self.focus_sessions[ctx.author.id] = task

    async def focus_timer(self, ctx, minutes):
        user_id = ctx.author.id
        try:
            # 等待指定時間
            await asyncio.sleep(minutes * 60)
            
            # 如果時間到了還沒被取消，代表成功
            if user_id in self.focus_sessions:
                bonus = minutes // 2 # 每 2 分鐘 +1 分
                await self.add_honor(user_id, bonus)
                await ctx.send(f"✅ **修煉完成！**\n{ctx.author.mention} 成功堅持了 `{minutes}` 分鐘沒有偷懶！\n榮譽值 `+{bonus}`！曼巴精神！🐍✨")
                del self.focus_sessions[user_id]
        except asyncio.CancelledError:
            # 任務被取消 (通常是因為偷玩遊戲被抓到)
            pass

    # 監聽：專注時偷玩遊戲
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        
        # 如果這個人正在專注模式
        if after.id in self.focus_sessions:
            # 檢查是否開始玩遊戲
            new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
            
            if new_game:
                # 抓到了！取消專注任務
                task = self.focus_sessions.pop(after.id)
                task.cancel()
                
                # 懲罰
                penalty = 50
                await self.add_honor(after.id, -penalty)
                
                # 找頻道罵人
                channel = after.guild.system_channel
                if not channel:
                    channel = discord.utils.find(lambda c: c.permissions_for(after.guild.me).send_messages, after.guild.text_channels)
                
                if channel:
                    msg = f"🚨 **抓到了！騙子！**\n{after.mention} 說要專注，結果偷偷打開了 **{new_game}**！\n**修煉失敗！榮譽值重扣 50 分！** 😡👎"
                    await channel.send(msg)
                    # 如果在語音，踢出
                    if after.voice:
                        await after.voice.disconnect()
                        await channel.send("👻 (並且被踢出了語音頻道)")

    # ==========================================
    # 📅 B. 每日簽到 (Daily Streak)
    # ==========================================
    @commands.command(aliases=["clockin", "ci"])
    async def checkin(self, ctx):
        """每日打卡，累積連勝"""
        user_id = ctx.author.id
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT current_streak, last_checkin_date FROM streaks WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            
            streak = 0
            last_date = None
            
            if row:
                streak = row[0]
                last_date = row[1]

            if last_date == today:
                return await ctx.send(f"⏳ {ctx.author.mention} 你今天已經打卡過了！目前連勝：`{streak}` 天。")
            
            # 判斷連勝
            if last_date == yesterday:
                new_streak = streak + 1
                msg_prefix = f"🔥 **連勝延續！**"
            else:
                new_streak = 1
                msg_prefix = f"⚠️ **紀錄中斷/開始！**" if streak > 0 else "📝 **開始打卡！**"

            # 計算獎勵 (連勝越多送越多，最高 +20)
            reward = min(new_streak * 2, 20)
            
            # 更新資料庫
            await db.execute("INSERT OR REPLACE INTO streaks (user_id, current_streak, last_checkin_date) VALUES (?, ?, ?)", (user_id, new_streak, today))
            await db.commit()
            
            # 加分
            await self.add_honor(user_id, reward)
            
            await ctx.send(f"{msg_prefix}\n{ctx.author.mention} 完成每日打卡！(第 `{new_streak}` 天)\n獲得榮譽 `+{reward}`！Keep going! 🏀")

    # ==========================================
    # 💬 C. 榮譽系統與監控 (Honor System)
    # ==========================================
    async def add_honor(self, user_id, amount):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (user_id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # 聊天監控 (不影響指令)
        if message.content.startswith("!"): return

        content = message.content.lower()
        change = 0
        response = ""

        if any(word in content for word in self.weak_words):
            change = -2
            response = random.choice(self.weak_roasts)
        elif any(word in content for word in self.strong_words):
            change = 2
            response = random.choice(self.strong_encourage)

        if change != 0:
            await self.add_honor(message.author.id, change)
            embed = discord.Embed(description=f"{message.author.mention} {response}", color=0x2ecc71 if change > 0 else 0xe74c3c)
            await message.channel.send(embed=embed)

    @commands.command()
    async def honor(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT points FROM honor WHERE user_id = ?", (target.id,))
            row = await cursor.fetchone()
            points = row[0] if row else 0
        
        # 稱號邏輯
        title = "🤡 飲水機守護神"
        color = 0x95a5a6
        if points >= 500: title, color = "🐍 黑曼巴 (The GOAT)", 0xf1c40f
        elif points >= 300: title, color = "⭐ 全明星 (All-Star)", 0x3498db
        elif points >= 100: title, color = "🏀 先發球員 (Starter)", 0x2ecc71
        elif points >= 0:   title, color = "🪑 萬年替補 (Bench)", 0xe67e22
        else: color = 0xe74c3c

        embed = discord.Embed(title=f"📜 {target.display_name} 的榮譽檔案", color=color)
        embed.add_field(name="階級稱號", value=f"**{title}**", inline=False)
        embed.add_field(name="榮譽點數", value=f"`{points}` 點", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command()
    async def rank(self, ctx):
        """查看榮譽排行榜"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id, points FROM honor ORDER BY points DESC LIMIT 10")
            rows = await cursor.fetchall()
        
        if not rows: return await ctx.send("📊 還沒人有榮譽分數！")
        
        embed = discord.Embed(title="🏆 曼巴榮譽排行榜", color=0xffd700)
        text = ""
        for idx, (uid, pts) in enumerate(rows):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"用戶({uid})"
            text += f"{idx+1}. **{name}** : `{pts}` pts\n"
        embed.description = text
        await ctx.send(embed=embed)

    @commands.command()
    async def respect(self, ctx, target: discord.Member):
        if target == ctx.author: return await ctx.send("❌ 不能致敬自己！")
        await self.vote(ctx, target, 10, "🫡")

    @commands.command()
    async def blame(self, ctx, target: discord.Member):
        if target == ctx.author: return await ctx.send("❌ 不能譴責自己！")
        await self.vote(ctx, target, -10, "👎")

    async def vote(self, ctx, target, amount, emoji):
        user_id = ctx.author.id
        today = datetime.now().strftime('%Y-%m-%d')
        
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT last_vote_date FROM honor WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row and row[0] == today:
                return await ctx.send(f"⏳ {ctx.author.mention} 今天投過票了！")
            
            await db.execute("INSERT OR REPLACE INTO honor (user_id, points, last_vote_date) VALUES (?, (SELECT points FROM honor WHERE user_id=?), ?)", (user_id, user_id, today))
            await self.add_honor(target.id, amount)
            await db.commit()
        
        await ctx.send(f"{emoji} {ctx.author.mention} 評價了 {target.mention}！ (榮譽 `{amount:+d}`)")

async def setup(bot):
    await bot.add_cog(Game(bot))

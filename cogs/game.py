import discord
from discord.ext import commands
import aiosqlite
import random
from datetime import datetime

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "honor_system.db"
        
        # --- 軟弱詞彙 (扣分) ---
        self.weak_words = ["累", "好累", "想睡", "睡覺", "放棄", "好難", "不想動", "休息", "明天再說", "擺爛"]
        self.weak_roasts = [
            "累了？這就是為什麼你永遠是替補！😤",
            "想休息？對手正在訓練呢！📉",
            "軟弱！曼巴精神不允許你說這句話！🚫",
            "我看錯你了，原來你只有這種程度？🤡"
        ]

        # --- 積極詞彙 (加分) ---
        self.strong_words = ["健身", "訓練", "加班", "寫扣", "唸書", "拼了", "努力", "堅持", "搞定", "練球"]
        self.strong_encourage = [
            "沒錯！這就是曼巴精神！🏀🔥",
            "保持專注！你正在通往偉大的路上！✨",
            "我看見你的努力了！繼續保持！💪",
            "凌晨四點的太陽會照亮你的！☀️"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            # 建立榮譽表 (user_id, points, last_vote_date)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS honor (
                    user_id INTEGER PRIMARY KEY, 
                    points INTEGER DEFAULT 0,
                    last_vote_date DATE
                )
            ''')
            await db.commit()

    # ---  helper: 取得稱號 ---
    def get_title(self, points):
        if points >= 500: return "🐍 黑曼巴 (The GOAT)"
        if points >= 300: return "⭐ 全明星 (All-Star)"
        if points >= 100: return "🏀 先發球員 (Starter)"
        if points >= 0:   return "🪑 萬年替補 (Bench)"
        return "🤡 飲水機守護神 (Clown)"

    # --- 👂 聊天室監聽功能 ---
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return

        content = message.content.lower()
        change = 0
        response = ""

        # 1. 檢查軟弱詞彙
        if any(word in content for word in self.weak_words):
            change = -2
            response = random.choice(self.weak_roasts)
        
        # 2. 檢查積極詞彙 (如果同時有，抵銷)
        elif any(word in content for word in self.strong_words):
            change = 2
            response = random.choice(self.strong_encourage)

        if change != 0:
            async with aiosqlite.connect(self.db_name) as db:
                # 更新分數
                await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (message.author.id,))
                await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (change, message.author.id))
                
                # 查詢最新分數
                cursor = await db.execute("SELECT points FROM honor WHERE user_id = ?", (message.author.id,))
                row = await cursor.fetchone()
                new_points = row[0] if row else 0
                await db.commit()

            # 發送回應
            title = self.get_title(new_points)
            embed = discord.Embed(description=f"{message.author.mention} {response}\n(榮譽值 `{change:+d}`，目前稱號：**{title}**)", color=0xffd700 if change > 0 else 0xff0000)
            await message.channel.send(embed=embed)

    # --- 🫡 致敬指令 ---
    @commands.command()
    async def respect(self, ctx, target: discord.Member):
        if target.bot or target == ctx.author: return await ctx.send("❌ 你不能致敬機器人或你自己！")
        
        await self.process_vote(ctx, target, 10, "🫡")

    # --- 👎 譴責指令 ---
    @commands.command()
    async def blame(self, ctx, target: discord.Member):
        if target.bot or target == ctx.author: return await ctx.send("❌ 你不能譴責機器人或你自己！")
        
        await self.process_vote(ctx, target, -10, "👎")

    async def process_vote(self, ctx, target, amount, emoji):
        today = datetime.now().strftime('%Y-%m-%d')
        user_id = ctx.author.id
        
        async with aiosqlite.connect(self.db_name) as db:
            # 檢查今天投過沒
            cursor = await db.execute("SELECT last_vote_date FROM honor WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            
            if row and row[0] == today:
                await ctx.send(f"⏳ {ctx.author.mention} 你今天已經行使過你的榮譽投票權了！明天再來。")
                return

            # 更新投票者的日期
            if row:
                await db.execute("UPDATE honor SET last_vote_date = ? WHERE user_id = ?", (today, user_id))
            else:
                await db.execute("INSERT INTO honor (user_id, points, last_vote_date) VALUES (?, 0, ?)", (user_id, today))

            # 更新被投票者的分數
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (target.id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (amount, target.id))
            
            # 查對方現在幾分
            cursor = await db.execute("SELECT points FROM honor WHERE user_id = ?", (target.id,))
            t_row = await cursor.fetchone()
            new_points = t_row[0]

            await db.commit()

        title = self.get_title(new_points)
        action = "致敬了" if amount > 0 else "譴責了"
        color = 0x2ecc71 if amount > 0 else 0xe74c3c
        
        embed = discord.Embed(title=f"{emoji} 榮譽評價更新", description=f"{ctx.author.mention} {action} {target.mention}！\n\n{target.display_name} 的榮譽值 `{amount:+d}`\n目前總分：`{new_points}`\n當前階級：**{title}**", color=color)
        await ctx.send(embed=embed)

    # --- 📊 查詢榮譽榜 ---
    @commands.command()
    async def honor(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT points FROM honor WHERE user_id = ?", (target.id,))
            row = await cursor.fetchone()
            points = row[0] if row else 0
        
        title = self.get_title(points)
        # 設定進度條顏色
        color = 0x95a5a6 # 預設灰
        if points >= 500: color = 0xf1c40f # 金
        elif points >= 300: color = 0x3498db # 藍
        elif points >= 100: color = 0x2ecc71 # 綠
        elif points < 0: color = 0xe74c3c # 紅

        embed = discord.Embed(title=f"📜 {target.display_name} 的榮譽檔案", color=color)
        embed.add_field(name="目前稱號", value=f"**{title}**", inline=False)
        embed.add_field(name="榮譽點數", value=f"`{points}` 點", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        
        # 評語
        if points < 0: embed.set_footer(text="評價：球隊毒瘤，請盡快反省。")
        elif points > 300: embed.set_footer(text="評價：球隊核心，曼巴精神的繼承者。")
        else: embed.set_footer(text="評價：還需努力，凌晨四點見。")

        await ctx.send(embed=embed)

    # --- 🏆 全伺服器排行榜 ---
    @commands.command()
    async def leaderboard(self, ctx):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id, points FROM honor ORDER BY points DESC LIMIT 10")
            rows = await cursor.fetchall()

        if not rows:
            return await ctx.send("📊 目前還沒有任何榮譽紀錄！")

        embed = discord.Embed(title="🏆 曼巴榮譽排行榜", color=0xffd700)
        text = ""
        for idx, (uid, pts) in enumerate(rows):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"用戶({uid})"
            title = self.get_title(pts)
            medal = ["🥇", "🥈", "🥉"][idx] if idx < 3 else f"{idx+1}."
            
            text += f"{medal} **{name}** (`{pts}` pts) - {title}\n"
        
        embed.description = text
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Game(bot))

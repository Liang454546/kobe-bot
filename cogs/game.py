import discord
from discord.ext import commands
import aiosqlite
import time
from datetime import datetime
import random
import asyncio

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {} 
        self.db_name = "game_stats.db"
        
        # --- 1. 遊戲偵測罵人語錄 (保留) ---
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

        # --- 2. 聊天室榮譽系統語錄 (新增) ---
        # 軟弱詞彙 (扣榮譽)
        self.weak_words = ["累", "好累", "想睡", "睡覺", "放棄", "好難", "不想動", "休息", "明天再說", "擺爛", "不想努力"]
        self.weak_roasts = [
            "累了？這就是為什麼你永遠是替補！😤 (榮譽 -2)",
            "想休息？你的對手正在訓練呢！📉 (榮譽 -2)",
            "軟弱！曼巴精神不允許你說這句話！🚫 (榮譽 -2)",
            "我看錯你了，原來你只有這種程度？🤡 (榮譽 -2)"
        ]

        # 積極詞彙 (加榮譽)
        self.strong_words = ["健身", "訓練", "加班", "寫扣", "唸書", "拼了", "努力", "堅持", "搞定", "練球", "開會"]
        self.strong_encourage = [
            "沒錯！這就是曼巴精神！🏀🔥 (榮譽 +2)",
            "保持專注！你正在通往偉大的路上！✨ (榮譽 +2)",
            "我看見你的努力了！繼續保持！💪 (榮譽 +2)",
            "凌晨四點的太陽會照亮你的！☀️ (榮譽 +2)"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            # 表格 1: 遊戲時間紀錄 (保留)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS playtime (
                    user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE
                )
            ''')
            # 表格 2: 榮譽系統 (新增)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS honor (
                    user_id INTEGER PRIMARY KEY, 
                    points INTEGER DEFAULT 0,
                    last_vote_date DATE
                )
            ''')
            await db.commit()

    # ==========================================
    # 🎯 功能 A: 遊戲偵測與監控 (保留原功能)
    # ==========================================
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game == old_game: return

        # 結束舊遊戲 (存檔)
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]

        # 開始新遊戲 (罵人 + 語音突襲)
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # 1. 準備罵人的話
            game_lower = new_game.lower()
            roast_content = next((text for kw, text in self.targeted_roasts.items() if kw in game_lower), None)
            if not roast_content:
                roast_content = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
            else:
                roast_content = f"{after.mention} {roast_content}"

            # 2. 找文字頻道
            target_names = ["chat", "general", "聊天", "公頻", "主頻道"]
            text_channel = discord.utils.find(lambda c: any(t in c.name.lower() for t in target_names) and c.permissions_for(after.guild.me).send_messages, after.guild.text_channels)
            if not text_channel:
                text_channel = discord.utils.find(lambda c: c.permissions_for(after.guild.me).send_messages, after.guild.text_channels)
            
            # 3. 語音突襲與發送
            if after.voice and after.voice.channel:
                voice_channel = after.voice.channel
                try:
                    if after.guild.voice_client is None:
                        await voice_channel.connect()
                    elif after.guild.voice_client.channel != voice_channel:
                        await after.guild.voice_client.move_to(voice_channel)
                    
                    if text_channel:
                        tts_msg = f"喂！{after.display_name}！我抓到你在偷玩 {new_game}！專心一點！"
                        await text_channel.send(tts_msg, tts=True)
                        await text_channel.send(f"🎙️ **語音查哨突襲！**\n{roast_content}")
                except:
                    pass
            else:
                if text_channel:
                    await text_channel.send(roast_content)

    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    # ==========================================
    # 🗣️ 功能 B: 聊天室榮譽系統 (Chat Monitor)
    # ==========================================
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
        
        # 2. 檢查積極詞彙
        elif any(word in content for word in self.strong_words):
            change = 2
            response = random.choice(self.strong_encourage)

        if change != 0:
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (message.author.id,))
                await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (change, message.author.id))
                
                cursor = await db.execute("SELECT points FROM honor WHERE user_id = ?", (message.author.id,))
                row = await cursor.fetchone()
                new_points = row[0] if row else 0
                await db.commit()

            title = self.get_title(new_points)
            color = 0x2ecc71 if change > 0 else 0xe74c3c
            embed = discord.Embed(description=f"{message.author.mention} {response}\n(目前榮譽：`{new_points}` 稱號：**{title}**)", color=color)
            await message.channel.send(embed=embed)

    def get_title(self, points):
        if points >= 500: return "🐍 黑曼巴 (The GOAT)"
        if points >= 300: return "⭐ 全明星 (All-Star)"
        if points >= 100: return "🏀 先發球員 (Starter)"
        if points >= 0:   return "🪑 萬年替補 (Bench)"
        return "🤡 飲水機守護神 (Clown)"

    # ==========================================
    # 📜 指令區 (Rank + Honor)
    # ==========================================

    # 1. 遊戲排名 (!rank) - 保留
    @commands.command()
    async def rank(self, ctx):
        try:
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute('SELECT user_id, SUM(seconds) as total FROM playtime GROUP BY user_id')
                rows = await cursor.fetchall()
                stats = {row[0]: row[1] for row in rows}
                
                # 加入即時時間
                current_time = time.time()
                for uid, session in self.active_sessions.items():
                    stats[uid] = stats.get(uid, 0) + int(current_time - session['start'])
                
                sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
                if not sorted_stats: return await ctx.send("📊 資料庫空空如也！")

                embed = discord.Embed(title="🏆 伺服器偷懶排行榜 (遊戲時長)", color=0xffd700)
                text = ""
                for idx, (uid, sec) in enumerate(sorted_stats):
                    m = ctx.guild.get_member(uid)
                    name = m.display_name if m else f"用戶({uid})"
                    status = "🎮" if uid in self.active_sessions else ""
                    text += f"{idx+1}. **{name}** {status}: {sec//3600}小時 {(sec%3600)//60}分\n"
                embed.add_field(name="名單", value=text)
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    # 2. 榮譽查詢 (!honor) - 新增
    @commands.command()
    async def honor(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT points FROM honor WHERE user_id = ?", (target.id,))
            row = await cursor.fetchone()
            points = row[0] if row else 0
        
        title = self.get_title(points)
        color = 0xf1c40f if points >= 100 else 0x95a5a6
        if points < 0: color = 0xe74c3c

        embed = discord.Embed(title=f"📜 {target.display_name} 的榮譽檔案", color=color)
        embed.add_field(name="目前稱號", value=f"**{title}**", inline=False)
        embed.add_field(name="榮譽點數", value=f"`{points}` 點", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    # 3. 榮譽致敬 (!respect) - 新增
    @commands.command()
    async def respect(self, ctx, target: discord.Member):
        if target.bot or target == ctx.author: return await ctx.send("❌ 無法對自己或機器人致敬！")
        await self.process_vote(ctx, target, 10, "🫡 致敬")

    # 4. 榮譽譴責 (!blame) - 新增
    @commands.command()
    async def blame(self, ctx, target: discord.Member):
        if target.bot or target == ctx.author: return await ctx.send("❌ 無法對自己或機器人譴責！")
        await self.process_vote(ctx, target, -10, "👎 譴責")

    # 投票處理邏輯
    async def process_vote(self, ctx, target, amount, action_name):
        today = datetime.now().strftime('%Y-%m-%d')
        user_id = ctx.author.id
        async with aiosqlite.connect(self.db_name) as db:
            # 檢查是否投過
            cursor = await db.execute("SELECT last_vote_date FROM honor WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row and row[0] == today:
                return await ctx.send(f"⏳ {ctx.author.mention} 你今天已經投過票了！明天再來。")

            # 更新投票紀錄
            if row: await db.execute("UPDATE honor SET last_vote_date = ? WHERE user_id = ?", (today, user_id))
            else: await db.execute("INSERT INTO honor (user_id, points, last_vote_date) VALUES (?, 0, ?)", (user_id, today))

            # 更新對方分數
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (target.id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (amount, target.id))
            
            # 取得新分數
            cursor = await db.execute("SELECT points FROM honor WHERE user_id = ?", (target.id,))
            t_row = await cursor.fetchone()
            new_points = t_row[0]
            await db.commit()

        title = self.get_title(new_points)
        color = 0x2ecc71 if amount > 0 else 0xe74c3c
        embed = discord.Embed(description=f"{ctx.author.mention} {action_name} {target.mention}！\n(對方榮譽 `{amount:+d}`，目前：`{new_points}` **{title}**)", color=color)
        await ctx.send(embed=embed)

    # 5. 榮譽排行榜 (!leaderboard) - 新增
    @commands.command()
    async def leaderboard(self, ctx):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id, points FROM honor ORDER BY points DESC LIMIT 10")
            rows = await cursor.fetchall()

        if not rows: return await ctx.send("📊 榮譽榜空空如也！")

        embed = discord.Embed(title="🏆 曼巴榮譽排行榜", color=0xffd700)
        text = ""
        for idx, (uid, pts) in enumerate(rows):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"用戶({uid})"
            title = self.get_title(pts)
            text += f"{idx+1}. **{name}** (`{pts}` pts) - {title}\n"
        
        embed.description = text
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Game(bot))

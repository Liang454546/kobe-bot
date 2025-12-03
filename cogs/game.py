import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta, timezone
import random

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        self.active_sessions = {}
        self.focus_sessions = {}
        self.voice_sessions = {}
        self.user_goals = {}
        
        # 冷卻系統
        self.chat_cooldowns = {}      
        self.roast_cooldowns = {}  
        self.emotion_cooldowns = {}

        # --- 1. 遊戲罵人語錄 (針對性) ---
        self.targeted_roasts = {
            "gta": ["這裡不是洛聖都，去現實生活努力吧！", "偷車能讓你變強嗎？去訓練！"],
            "nba": ["手指動得比腳快有什麼用？", "玩 2K 建球員？不如去建設你自己的人生！"],
            "league of legends": ["又在打 LOL？心態炸裂了嗎？", "別再雷人了！去現實生活爬分！"],
            "valorant": ["槍法準有什麼用？現實目標打得中嗎？", "急停射擊？你的學業進度也急停了嗎？"],
            "apex": ["APEX？你的肝還好嗎？", "整天當滋崩狗？做人光明磊落一點！"],
            "原神": ["啟動？給我把書桌前的燈啟動！", "你的人生抽不到保底的！"],
            "honkai": ["星穹鐵道？你的未來也要出軌了嗎？"]
        }
        
        # --- 2. 通用罵人語錄 (隨機) ---
        self.general_roasts = [
            "抓到了！{member} 玩 **{game}**！不用唸書嗎？😡",
            "看到 {member} 玩 **{game}**，曼巴精神去哪了？",
            "你的肝是鐵做的嗎？還在玩？",
            "這時候玩遊戲？你的競爭對手正在訓練呢！",
            "嗶嗶！裁判！{member} 犯規！驅逐出場！",
            "你對得起凌晨四點的太陽嗎？你只對得起你的床！"
        ]

        # --- 3. 榮譽系統語錄 ---
        self.weak_words = ["累", "好累", "想睡", "放棄", "好難", "不想動", "休息", "擺爛", "不想努力"]
        self.weak_responses = [
            "累了？這就是為什麼你永遠是替補！😤",
            "想休息？休息是留給死人的！📉",
            "軟弱！曼巴精神不允許你說這句話！🚫",
            "藉口！全是藉口！"
        ]
        
        self.strong_words = ["健身", "訓練", "加班", "寫扣", "唸書", "拼了", "努力", "堅持", "搞定"]
        self.strong_responses = [
            "沒錯！這就是曼巴精神！🏀🔥",
            "保持專注！你正在通往偉大的路上！✨",
            "我看見你的努力了！繼續保持！💪",
            "這才是我們要的態度！"
        ]

        # --- 4. Kobe 語錄 (模擬對話用) ---
        self.kobe_quotes = [
            "Mamba Out. 🎤",
            "Man, what can I say? 🤷‍♂️",
            "第二名就是頭號輸家。",
            "你見過凌晨四點的洛杉磯嗎？",
            "那些殺不死你的，只會讓你更強。",
            "如果你害怕失敗，那你已經輸了。",
            "低頭不是認輸，是要看清自己的路。",
            "別問我為什麼這麼嚴格，問問你自己為什麼這麼軟弱。",
            "Soft. 🥚"
        ]

        self.emotional_words = ["爆氣", "生氣", "想哭", "哭了", "崩潰", "好煩", "不爽", "輸了"]
        self.emotional_responses = [
            "哭？眼淚能幫你贏球嗎？把情緒轉化為動力！🔥",
            "生氣了？很好。記住這種感覺，下次贏回來。",
            "崩潰是軟蛋的權利。你是軟蛋嗎？站起來！",
            "這世界不在乎你的感受，只在乎你的成果。"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS streaks (user_id INTEGER PRIMARY KEY, current_streak INTEGER DEFAULT 0, last_checkin_date DATE)')
            await db.commit()
        self.weekend_check.start()

    async def cog_unload(self):
        self.weekend_check.cancel()

    # ==========================================
    # 📅 自動任務：週末地獄提醒
    # ==========================================
    @tasks.loop(minutes=1)
    async def weekend_check(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        channel = self.get_text_channel(self.bot.guilds[0]) if self.bot.guilds else None
        if not channel: return

        if now.weekday() == 4 and now.hour == 22 and now.minute == 0:
            await channel.send("🔥 **週五晚上！** 別人都在狂歡，這正是你超越他們的時候。別鬆懈！🐍")
        if now.weekday() == 5 and now.hour == 8 and now.minute == 0:
            await channel.send("☀️ **週六早晨！** 週末不是藉口。當別人在睡懶覺，你應該在訓練。Mamba Mentality！🏀")

    @weekend_check.before_loop
    async def before_weekend_check(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 🎯 遊戲監控 & 🔊 語音訓練
    # ==========================================
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return
        channel = self.get_text_channel(member.guild)

        # 加入語音
        if before.channel is None and after.channel is not None:
            self.voice_sessions[member.id] = time.time()
            if self.active_sessions.get(member.id):
                game = self.active_sessions[member.id]['game']
                if channel: await channel.send(f"🎙️ **語音查哨！** {member.mention} 帶著 **{game}** 進語音？專心一點！")

        # 離開語音
        if before.channel is not None and after.channel is None:
            if member.id in self.voice_sessions:
                mins = int(time.time() - self.voice_sessions.pop(member.id)) // 60
                if mins < 1: return
                
                if mins < 10: change, msg = -5, f"進去 {mins} 分鐘喝水的嗎？軟蛋！"
                elif mins > 60: change, msg = 10, f"紮實的 {mins} 分鐘訓練。保持下去！"
                else: change, msg = 2, f"訓練了 {mins} 分鐘。"
                
                await self.add_honor(member.id, change)
                if channel: await channel.send(f"📊 **訓練結算** {member.mention}\n{msg} (榮譽 `{change:+d}`)")

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)
        channel = self.get_text_channel(after.guild)

        if new_game == old_game: return

        # 專注模式偷玩
        if user_id in self.focus_sessions and new_game:
            self.focus_sessions[user_id].cancel()
            del self.focus_sessions[user_id]
            await self.add_honor(user_id, -50)
            if channel:
                await channel.send(f"🚨 **抓到了！騙子！**\n{after.mention} 專注時偷玩 **{new_game}**！榮譽 -50！😡")
                if after.voice: await after.voice.disconnect()
            return

        # 遊戲結束
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]
                    # 賽後採訪 (隨機觸發)
                    if duration > 600 and channel and random.random() < 0.5:
                        mins = duration // 60
                        quotes = ["這段時間你學到了什麼？", "是在浪費生命嗎？", "有進步嗎？還是原地踏步？"]
                        await channel.send(f"🎤 **賽後採訪** {after.mention}\n剛玩了 {mins} 分鐘。{random.choice(quotes)}")

        # 遊戲開始 (罵人)
        if new_game:
            # 檢查冷卻 (5分鐘)
            now = time.time()
            if user_id in self.roast_cooldowns and now - self.roast_cooldowns[user_id] < 300:
                return
            self.roast_cooldowns[user_id] = now

            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # 挑選罵人語錄
            game_lower = new_game.lower()
            msg = None
            for kw, lines in self.targeted_roasts.items():
                if kw in game_lower:
                    msg = random.choice(lines)
                    break
            
            if not msg: msg = random.choice(self.general_roasts).format(member=after.mention, game=new_game)
            else: msg = f"{after.mention} {msg}"

            if channel: await channel.send(msg)
            
            # 語音查哨
            if after.voice and after.voice.channel:
                try:
                    vc = after.guild.voice_client
                    if not vc: await after.voice.channel.connect()
                    elif vc.channel != after.voice.channel: await vc.move_to(after.voice.channel)
                    if channel: await channel.send(f"🎙️ **語音查哨！** (盯著你...)")
                except: pass

    # ==========================================
    # 💬 聊天監控 (單機版)
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
        content = message.content.lower()

        # 1. 聊天互動 (被標記)
        if self.bot.user in message.mentions:
            await message.reply(random.choice(self.kobe_quotes))
            return

        # 2. 關鍵字監控 (有冷卻 60s)
        now = time.time()
        if user_id in self.chat_cooldowns and now - self.chat_cooldowns[user_id] < 60: return 

        change, response = 0, ""
        
        # 情緒字眼
        if any(w in content for w in self.emotional_words):
             change, response = 0, random.choice(self.emotional_responses)
             self.chat_cooldowns[user_id] = now
             await message.channel.send(embed=discord.Embed(description=f"{message.author.mention} {response}", color=0x3498db))
             return

        # 努力 vs 軟弱
        if any(w in content for w in self.weak_words):
            change, response = -2, random.choice(self.weak_responses)
        elif any(w in content for w in self.strong_words):
            change, response = 2, random.choice(self.strong_responses)

        if change != 0:
            self.chat_cooldowns[user_id] = now
            await self.add_honor(user_id, change)
            color = 0x2ecc71 if change > 0 else 0xe74c3c
            await message.channel.send(embed=discord.Embed(description=f"{message.author.mention} {response}", color=color))

    # ==========================================
    # 📜 其他指令 (目標、簽到...)
    # ==========================================
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

    @commands.command()
    async def goal(self, ctx, *, content: str):
        if ctx.author.id in self.user_goals: return await ctx.send(f"⚠️ 還有未完成目標：**{self.user_goals[ctx.author.id]}**")
        self.user_goals[ctx.author.id] = content
        await ctx.send(f"📌 **目標鎖定！** {ctx.author.mention} 立誓：**{content}**")

    @commands.command()
    async def done(self, ctx):
        if ctx.author.id not in self.user_goals: return await ctx.send("❓ 沒目標。")
        content = self.user_goals.pop(ctx.author.id)
        await self.add_honor(ctx.author.id, 20)
        await ctx.send(embed=discord.Embed(title="✅ 目標達成！", description=f"{ctx.author.mention} 完成：**{content}**\n榮譽 `+20`", color=0x2ecc71))

    @commands.command()
    async def giveup(self, ctx):
        if ctx.author.id not in self.user_goals: return await ctx.send("❓ 沒目標。")
        content = self.user_goals.pop(ctx.author.id)
        await self.add_honor(ctx.author.id, -20)
        await ctx.send(f"🏳️ **軟蛋！** {ctx.author.mention} 放棄：**{content}** (榮譽 `-20`)")

    @commands.command()
    async def focus(self, ctx, minutes: int):
        if minutes < 1 or minutes > 180: return await ctx.send("❌ 限 1~180 分鐘")
        if ctx.author.id in self.focus_sessions: return await ctx.send("⚠️ 專注中！")
        await ctx.send(f"🔒 **專注啟動！** `{minutes}` 分鐘。\n偷玩 = **榮譽 -50 + 踢出語音**！")
        self.focus_sessions[ctx.author.id] = asyncio.create_task(self.focus_timer(ctx, minutes))

    async def focus_timer(self, ctx, minutes):
        try:
            await asyncio.sleep(minutes * 60)
            if ctx.author.id in self.focus_sessions:
                await self.add_honor(ctx.author.id, minutes // 2)
                await ctx.send(f"✅ **修煉完成！** {ctx.author.mention} 榮譽 `+{minutes//2}`！")
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
            await ctx.send(f"🔥 **打卡成功！** {ctx.author.mention} 連勝 `{new_streak}` 天 (榮譽 `+{reward}`)！")

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

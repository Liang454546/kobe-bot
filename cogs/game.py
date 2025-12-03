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
        
        # 冷卻系統
        self.chat_cooldowns = {}      
        self.ai_roast_cooldowns = {}  
        self.ai_chat_cooldowns = {}   
        
        # --- 1. 設定 AI (Gemini Pro) ---
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel('gemini-pro')
                self.has_ai = True
                print("✅ AI 模組啟動成功")
            except:
                self.has_ai = False
        else:
            self.has_ai = False

        # --- 2. 備用單機語錄 (當 AI 壞掉時自動啟用) ---
        # 這些語錄讓機器人就算斷網也能運作
        self.backup_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？",
            "你的肝是鐵做的嗎？還在玩？去訓練！",
            "嗶嗶！裁判！{member} 犯規！驅逐出場！",
            "這時候玩遊戲？你的競爭對手正在訓練呢！"
        ]
        
        self.kobe_quotes = [
            "Mamba Out. 🎤",
            "Man, what can I say? 🤷‍♂️",
            "第二名就是頭號輸家。",
            "那些殺不死你的，只會讓你更強。",
            "如果你害怕失敗，那你已經輸了。",
            "Soft. 🥚",
            "別問我為什麼這麼嚴格，問問你自己為什麼這麼軟弱。"
        ]

        self.weak_words = ["累", "好累", "想睡", "放棄", "好難", "不想動", "休息", "擺爛"]
        self.strong_words = ["健身", "訓練", "加班", "寫扣", "唸書", "拼了", "努力", "堅持"]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS streaks (user_id INTEGER PRIMARY KEY, current_streak INTEGER DEFAULT 0, last_checkin_date DATE)')
            await db.commit()

    # ==========================================
    # 🧠 AI 核心：智慧切換 (Smart Switch)
    # ==========================================
    async def ask_kobe(self, prompt, user_id, cooldown_dict, cooldown_time=30):
        # 1. 如果沒 AI 或冷卻中，直接回傳 None (讓外部用備用)
        if not self.has_ai: return None
        
        now = time.time()
        if user_id in cooldown_dict:
            if now - cooldown_dict[user_id] < cooldown_time: return None
        
        cooldown_dict[user_id] = now

        try:
            # 嘗試呼叫 AI
            system_prompt = (
                "你是 Kobe Bryant。個性：毒舌、極度好勝、看不起軟蛋。"
                "請用繁體中文(台灣)。回答簡短有力(30字內)，多用 emoji (🏀🐍)。"
                f"情況：{prompt}"
            )
            response = await asyncio.to_thread(self.model.generate_content, system_prompt)
            return response.text
        except:
            # 🔥 關鍵：如果 AI 報錯，我們不顯示 ERROR，而是回傳 None
            # 這樣外面的程式碼就會自動切換成「備用單機語錄」
            return None

    # ==========================================
    # 🎯 遊戲監控
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

        # B. 遊戲結束 (存檔 + 偶爾採訪)
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]
                    
                    # 玩超過 10 分鐘，且 AI 成功時才採訪
                    if duration > 600 and channel:
                        mins = duration // 60
                        prompt = f"{after.display_name} 玩了 {mins} 分鐘 {old_game}。質問他學到了什麼？"
                        interview = await self.ask_kobe(prompt, user_id, self.ai_chat_cooldowns, 0)
                        if interview: # 只有 AI 成功才發送，失敗就安靜
                            await channel.send(f"🎤 **賽後毒舌採訪** {after.mention}\n{interview}")

        # C. 遊戲開始 (AI 罵人 -> 失敗則用備用)
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # 1. 先試試看 AI
            roast_msg = await self.ask_kobe(f"這軟蛋開始玩 {new_game} 了，罵他。", user_id, self.ai_roast_cooldowns, 300)
            
            # 2. 如果 AI 失敗 (回傳 None)，就用備用字典
            if not roast_msg:
                roast_text = random.choice(self.backup_roasts).format(member=after.mention, game=new_game)
                roast_msg = f"{after.mention} {roast_text}"
            else:
                roast_msg = f"{after.mention} {roast_msg}"

            # 3. 發送
            if channel: await channel.send(roast_msg)
            
            # 語音查哨
            if after.voice and after.voice.channel:
                try:
                    vc = after.guild.voice_client
                    if not vc: await after.voice.channel.connect()
                    elif vc.channel != after.voice.channel: await vc.move_to(after.voice.channel)
                    if channel: await channel.send(f"🎙️ **語音查哨中...** (盯著你)")
                except: pass

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
    # 💬 聊天監控 (智慧切換)
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

        # 1. 對話 (被標記)
        if self.bot.user in message.mentions:
            async with message.channel.typing():
                # 嘗試 AI
                reply = await self.ask_kobe(f"用戶說：{content}", user_id, self.ai_chat_cooldowns, 5)
                # 失敗就隨機回一句 Kobe 名言
                if not reply: reply = random.choice(self.kobe_quotes)
                await message.reply(reply)
            return

        # 2. 關鍵字/藉口粉碎
        now = time.time()
        if user_id in self.chat_cooldowns and now - self.chat_cooldowns[user_id] < 60: return 

        change, response = 0, ""
        
        # 嘗試用 AI 判斷 (高科技)
        ai_comment = None
        if self.has_ai:
            try:
                # 簡單分析，不呼叫複雜 API 以省流
                if any(w in content for w in self.weak_words):
                    change, ai_prompt = -5, f"用戶說『{content}』找藉口。罵他。"
                elif any(w in content for w in self.strong_words):
                    change, ai_prompt = 5, f"用戶說『{content}』很努力。誇他。"
                
                if change != 0:
                    ai_comment = await self.ask_kobe(ai_prompt, user_id, {}, 0)
            except: pass

        # 如果 AI 沒反應，用關鍵字 (低科技但穩定)
        if not ai_comment:
            if any(w in content for w in self.weak_words):
                change, response = -2, "累了？這是軟蛋的藉口！😤"
            elif any(w in content for w in self.strong_words):
                change, response = 2, "沒錯！保持曼巴精神！🏀"
        else:
            response = ai_comment

        if change != 0:
            self.chat_cooldowns[user_id] = now
            await self.add_honor(user_id, change)
            color = 0x2ecc71 if change > 0 else 0xe74c3c
            await message.channel.send(embed=discord.Embed(description=f"{message.author.mention} {response}", color=color))

    # ==========================================
    # 📜 其他指令 (目標、簽到...)
    # ==========================================
    @commands.command()
    async def goal(self, ctx, *, content: str):
        if ctx.author.id in self.user_goals: return await ctx.send(f"⚠️ 你還有未完成目標：**{self.user_goals[ctx.author.id]}**")
        self.user_goals[ctx.author.id] = content
        await ctx.send(f"📌 **目標鎖定！**\n{ctx.author.mention} 立誓要：**{content}**")

    @commands.command()
    async def done(self, ctx):
        if ctx.author.id not in self.user_goals: return await ctx.send("❓ 沒目標。")
        content = self.user_goals.pop(ctx.author.id)
        await self.add_honor(ctx.author.id, 20)
        # AI 誇獎或備用誇獎
        comment = await self.ask_kobe(f"用戶完成目標：{content}。稱讚他。", ctx.author.id, {}, 0) or "幹得好。這就是紀律。"
        await ctx.send(embed=discord.Embed(title="✅ 目標達成！", description=f"{ctx.author.mention} 完成：**{content}**\n🐍 Kobe: {comment}\n(榮譽 `+20`)", color=0x2ecc71))

    @commands.command()
    async def giveup(self, ctx):
        if ctx.author.id not in self.user_goals: return await ctx.send("❓ 沒目標。")
        content = self.user_goals.pop(ctx.author.id)
        await self.add_honor(ctx.author.id, -20)
        await ctx.send(f"🏳️ **軟蛋行為！**\n{ctx.author.mention} 放棄了目標：**{content}**\n(榮譽 `-20`)")

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
                bonus = minutes // 2
                await self.add_honor(ctx.author.id, bonus)
                await ctx.send(f"✅ **修煉完成！** {ctx.author.mention} 榮譽 `+{bonus}`！")
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

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

        # 榮譽目標系統（你原本缺）
        self.user_goals = {}

        # 冷卻系統
        self.chat_cooldowns = {}      
        self.ai_roast_cooldowns = {}  
        self.ai_chat_cooldowns = {}   

        # ====== Gemini 初始化 ======
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
                self.has_ai = True
                print("✅ Gemini 2.0 啟動成功")
            except Exception as e:
                print(f"❌ Gemini 啟動失敗: {e}")
                self.has_ai = False
        else:
            print("⚠️ 警告：找不到 GEMINI_API_KEY")
            self.has_ai = False

        # 備用語錄
        self.targeted_roasts = {
            "gta": "俠盜獵車手？🚗 這裡不是洛聖都，去努力工作吧！",
            "nba": "玩 NBA 2K？🏀 手指動得比腳快有什麼用？去球場流汗！",
            "league of legends": "又在打 LOL？💀 你的心態炸裂了嗎？",
            "valorant": "特戰英豪？槍法再準，現實生活打不中目標有什麼用？",
            "apex": "APEX？你的肝還好嗎？別再當滋崩狗了！",
            "原神": "啟動？😱 給我把書桌前的燈啟動！"
        }

        self.default_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？",
        ]

        self.weak_words = ["累", "好累", "想睡", "放棄", "好難", "不想動", "休息", "擺爛"]
        self.strong_words = ["健身", "訓練", "加班", "寫扣", "唸書", "拼了", "努力", "堅持"]


    # ====== 資料庫初始化 ======
    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS streaks (user_id INTEGER PRIMARY KEY, current_streak INTEGER DEFAULT 0, last_checkin_date DATE)')
            await db.commit()


    # ====== Gemini AI ---- ask Kobe ======
    async def ask_kobe(self, prompt, user_id, cooldown_dict, cooldown_time=30):
        if not self.has_ai:
            return None

        # 冷卻
        now = time.time()
        if user_id in cooldown_dict:
            if now - cooldown_dict[user_id] < cooldown_time:
                return None
        cooldown_dict[user_id] = now

        try:
            system_prompt = (
                "你是 Kobe Bryant。語氣溫馨 有時兇 不恭維 討厭玩nba2k 的人 要狠 像人類。"
                "請用繁體中文台灣，回答 30 字內，加入大量 emoji。"
                f"情境：{prompt}"
            )

            # Gemini 2.0 Flash 需要用 to_thread 避免阻塞
            response = await asyncio.to_thread(self.model.generate_content, contents=system_prompt)

            # 修正回傳格式（新 SDK 回傳 response.text）
            return getattr(response, "text", None)

        except Exception as e:
            print("AI Error:", e)
            return None


    # ====== Presence Update（偵測遊戲） ======
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot:
            return

        user_id = after.id

        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game == old_game:
            return

        channel = self.get_text_channel(after.guild)

        # 專注偷玩
        if user_id in self.focus_sessions and new_game:
            task = self.focus_sessions.pop(user_id)
            task.cancel()
            await self.add_honor(user_id, -50)
            if channel:
                await channel.send(f"🚨 抓到了！{after.mention} 專注時偷玩 **{new_game}**！榮譽 -50！")
                if after.voice:
                    await after.voice.disconnect()
            return

        # 遊戲結束 → 存資料 + 賽後 Kobe 訪問
        if old_game:
            if user_id in self.active_sessions:
                s = self.active_sessions[user_id]
                if s["game"] == old_game:
                    duration = int(time.time() - s["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]

                    if duration > 600 and channel:
                        mins = duration // 60
                        prompt = f"{after.display_name} 玩了 {mins} 分鐘 {old_game}。質問他學到了什麼？"
                        interview = await self.ask_kobe(prompt, user_id, self.ai_chat_cooldowns, 0)
                        if interview:
                            await channel.send(f"🎤 賽後採訪 {after.mention}\n{interview}")

        # 遊戲開始
        if new_game:
            self.active_sessions[user_id] = {
                "game": new_game,
                "start": time.time()
            }

            roast = await self.ask_kobe(
                f"這軟蛋開始玩 {new_game} 了，罵他為什麼不去訓練。",
                user_id,
                self.ai_roast_cooldowns,
                300
            )

            # AI 失敗 → 備用語錄
            if not roast:
                gl = new_game.lower()
                roast_text = next((t for k, t in self.targeted_roasts.items() if k in gl), None)
                if not roast_text:
                    roast_text = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
                roast = f"{after.mention} {roast_text}"
            else:
                roast = f"{after.mention} {roast}"

            if channel:
                await channel.send(roast)


    # ====== 存遊戲時數 ======
    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)",
                             (user_id, game_name, seconds, today))
            await db.commit()


    # ====== 找頻道 ======
    def get_text_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        c = discord.utils.find(
            lambda x: any(t in x.name.lower() for t in target)
            and x.permissions_for(guild.me).send_messages,
            guild.text_channels
        )
        return c or discord.utils.find(
            lambda x: x.permissions_for(guild.me).send_messages,
            guild.text_channels
        )


    # ====== 榮譽 ======
    async def add_honor(self, user_id, amount):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)",
                             (user_id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?",
                             (amount, user_id))
            await db.commit()


    # ====== 聊天監控 ======
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.content.startswith("!"):
            return

        user_id = message.author.id
        content = message.content
        now = time.time()

        # ─── AI 對話 ───
        if (
            self.bot.user in message.mentions or
            (message.reference and message.reference.resolved and message.reference.resolved.author == self.bot.user)
        ):
            async with message.channel.typing():
                reply = await self.ask_kobe(
                    f"用戶說：{content}",
                    user_id,
                    self.ai_chat_cooldowns,
                    5
                )
                if reply:
                    await message.reply(reply)
                else:
                    await message.reply("我在訓練中。🏀")
            return

        # ─── 藉口偵測 (Gemini) ───
        if self.has_ai:
            if user_id not in self.chat_cooldowns or now - self.chat_cooldowns[user_id] >= 60:
                try:
                    prompt = f"分析『{content}』。軟弱回'WEAK'，努力回'STRONG'，普通回'NORMAL'。只回答一字。"
                    response = await asyncio.to_thread(self.model.generate_content, prompt)
                    result = getattr(response, "text", "").strip().upper()

                    if "WEAK" in result:
                        change = -5
                        comment = await self.ask_kobe(
                            f"用戶說『{content}』，臭罵他。",
                            user_id,
                            {},
                            0
                        )
                    elif "STRONG" in result:
                        change = 5
                        comment = await self.ask_kobe(
                            f"用戶說『{content}』，稱讚他。",
                            user_id,
                            {},
                            0
                        )
                    else:
                        change = 0
                        comment = None

                    if change != 0 and comment:
                        self.chat_cooldowns[user_id] = now
                        await self.add_honor(user_id, change)

                        color = 0x2ecc71 if change > 0 else 0xe74c3c
                        embed = discord.Embed(
                            description=f"{message.author.mention} {comment}\n(AI 榮譽 `{change:+}`)",
                            color=color
                        )
                        await message.channel.send(embed=embed)
                        return
                except:
                    pass

        # ─── 備用詞判斷 ───
        change = 0
        if any(w in content for w in self.weak_words):
            change = -2
            response = "累？你這叫累？😤"
        elif any(w in content for w in self.strong_words):
            change = 2
            response = "不錯，這才像話。🏀"

        if change != 0:
            self.chat_cooldowns[user_id] = now
            await self.add_honor(user_id, change)
            color = 0x2ecc71 if change > 0 else 0xe74c3c
            embed = discord.Embed(
                description=f"{message.author.mention} {response}\n(榮譽 `{change:+}`)",
                color=color
            )
            await message.channel.send(embed=embed)


    # ====== 指令：goal ======
    @commands.command()
    async def goal(self, ctx, *, content: str):
        if ctx.author.id in self.user_goals:
            return await ctx.send(f"⚠️ 你還有未完成目標：**{self.user_goals[ctx.author.id]}**")

        self.user_goals[ctx.author.id] = content
        await ctx.send(f"📌 目標設定成功！{ctx.author.mention}：**{content}**")


    # ====== 指令：done ======
    @commands.command()
    async def done(self, ctx):
        if ctx.author.id not in self.user_goals:
            return await ctx.send("❓ 你沒有目標可完成。")

        content = self.user_goals.pop(ctx.author.id)
        await self.add_honor(ctx.author.id, 20)

        comment = await self.ask_kobe(
            f"用戶完成目標：{content}，稱讚他。",
            ctx.author.id,
            {},
            0
        ) or "幹得漂亮。"

        embed = discord.Embed(
            title="✅ 目標完成",
            description=f"{ctx.author.mention} 完成：**{content}**\n🐍 Kobe: {comment}\n(榮譽 `+20`)",
            color=0x2ecc71
        )
        await ctx.send(embed=embed)


    # ====== 指令：giveup ======
    @commands.command()
    async def giveup(self, ctx):
        if ctx.author.id not in self.user_goals:
            return await ctx.send("❓ 你沒有目標可放棄。")

        content = self.user_goals.pop(ctx.author.id)
        await self.add_honor(ctx.author.id, -20)

        await ctx.send(f"🏳️ 軟蛋！{ctx.author.mention} 放棄：**{content}** (榮譽 `-20`)")




    # ====== 指令：專注 ======
    @commands.command()
    async def focus(self, ctx, minutes: int):
        if minutes < 1 or minutes > 180:
            return await ctx.send("❌ 請輸入 1~180 分鐘")

        if ctx.author.id in self.focus_sessions:
            return await ctx.send("⚠️ 你已經在專注中！")

        await ctx.send(f"🔒 專注模式啟動 `{minutes}` 分鐘。\n偷玩 = **榮譽 -50 + 踢語音**!")

        self.focus_sessions[ctx.author.id] = asyncio.create_task(
            self.focus_timer(ctx, minutes)
        )

    async def focus_timer(self, ctx, minutes):
        try:
            await asyncio.sleep(minutes * 60)
            if ctx.author.id in self.focus_sessions:
                await self.add_honor(ctx.author.id, minutes // 2)
                await ctx.send(f"✅ 修煉完成！{ctx.author.mention} 榮譽 `+{minutes//2}`")
                del self.focus_sessions[ctx.author.id]
        except asyncio.CancelledError:
            pass


    # ====== 指令：每日打卡 ======
    @commands.command(aliases=["ci"])
    async def checkin(self, ctx):
        user_id = ctx.author.id
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        async with aiosqlite.connect(self.db_name) as db:
            row = await (await db.execute(
                "SELECT current_streak, last_checkin_date FROM streaks WHERE user_id = ?",
                (user_id,)
            )).fetchone()

            streak, last = (row[0], row[1]) if row else (0, None)

            if last == today:
                return await ctx.send(f"⏳ 今天已打卡！連勝 `{streak}` 天。")

            new_streak = streak + 1 if last == yesterday else 1
            reward = min(new_streak * 2, 20)

            await db.execute(
                "INSERT OR REPLACE INTO streaks (user_id, current_streak, last_checkin_date) VALUES (?, ?, ?)",
                (user_id, new_streak, today)
            )
            await db.commit()

        await self.add_honor(user_id, reward)
        await ctx.send(f"🔥 打卡成功！連勝 `{new_streak}` 天 (榮譽 `+{reward}`)")


    # ====== 指令：榮譽查詢 ======
    @commands.command()
    async def honor(self, ctx, target: discord.Member = None):
        target = target or ctx.author
        async with aiosqlite.connect(self.db_name) as db:
            row = await (await db.execute(
                "SELECT points FROM honor WHERE user_id = ?",
                (target.id,)
            )).fetchone()

        points = row[0] if row else 0
        await ctx.send(f"🏆 {target.mention} 的榮譽值：**{points}**")


async def setup(bot):
    await bot.add_cog(Game(bot))


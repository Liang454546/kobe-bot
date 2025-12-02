import discord
from discord.ext import commands
import aiosqlite
import time
from datetime import datetime, timedelta
import random
import asyncio 

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {} 
        self.db_name = "game_stats.db"
        
        # --- 1. 針對特定遊戲的罵人清單 ---
        self.targeted_roasts = {
            "gta": "俠盜獵車手？🚗 這裡不是洛聖都，這裡是現實世界！快去努力工作！",
            "grand theft auto": "還在 Grand Theft Auto？除了偷車你還會什麼？去偷點時間來唸書吧！",
            "nba": "玩 NBA 2K？🏀 手指動得比腳快有什麼用？去球場流汗！",
            "league of legends": "又在打 LOL？💀 心態炸裂了嗎？關掉它！",
            "valorant": "特戰英豪？槍法再準，現實生活射不中目標有什麼用？",
            "apex": "APEX？你的肝還好嗎？別再當滋崩狗了！",
            "原神": "啟動？😱 給我把書桌前的燈啟動！別再抽卡了！"
        }
        
        # --- 2. 通用罵人清單 ---
        self.default_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？",
            "嗶嗶！裁判！{member} 在玩 **{game}** 犯規！"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS playtime (
                    user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS economy (
                    user_id INTEGER PRIMARY KEY, 
                    balance INTEGER DEFAULT 0,
                    last_daily_claim DATE
                )
            ''')
            await db.commit()

    # --- 遊戲偵測邏輯 ---
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game == old_game: return

        # 結束舊遊戲 (結算)
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]

        # 開始新遊戲 (罵人)
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # --- 🔍 修正後的找頻道邏輯 ---
            target_channels = ["general", "chat", "聊天", "主頻道", "公頻", "閒聊"]
            channel = None
            
            # 1. 先嘗試找名字裡有「general, chat...」的文字頻道
            for c in after.guild.text_channels:
                if c.permissions_for(after.guild.me).send_messages:
                    if any(name in c.name.lower() for name in target_channels):
                        channel = c
                        break
            
            # 2. 如果沒找到，就找「第一個」機器人能講話的文字頻道 (放棄 System Channel)
            if not channel:
                for c in after.guild.text_channels:
                    if c.permissions_for(after.guild.me).send_messages:
                        channel = c
                        break
            
            # 發送訊息
            if channel:
                game_lower = new_game.lower()
                msg = None
                for kw, text in self.targeted_roasts.items():
                    if kw in game_lower:
                        msg = f"{after.mention} {text}"; break
                if not msg:
                    msg = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
                await channel.send(msg)

    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    # --- 💰 經濟指令 ---

    @commands.command()
    async def wallet(self, ctx):
        user_id = ctx.author.id
        today_str = datetime.now().strftime('%Y-%m-%d')
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT balance, last_daily_claim FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            balance = row[0] if row else 0
            last_claim = row[1] if row else None

            msg = f"💰 **{ctx.author.display_name} 的錢包**\n目前餘額：`{balance}` 曼巴幣\n"

            if last_claim != today_str:
                cursor = await db.execute("SELECT SUM(seconds) FROM playtime WHERE user_id = ? AND last_played = ?", (user_id, yesterday_str))
                play_row = await cursor.fetchone()
                yesterday_seconds = play_row[0] if play_row[0] else 0
                
                if yesterday_seconds < 3600: # 1小時內
                    reward = 10
                    new_balance = balance + reward
                    if row:
                        await db.execute("UPDATE economy SET balance = ?, last_daily_claim = ? WHERE user_id = ?", (new_balance, today_str, user_id))
                    else:
                        await db.execute("INSERT INTO economy (user_id, balance, last_daily_claim) VALUES (?, ?, ?)", (reward, today_str, user_id))
                    await db.commit()
                    msg += f"\n🎁 **每日結算：** 昨天你很自律！獲得 `+10` 幣！"
                else:
                    if row:
                        await db.execute("UPDATE economy SET last_daily_claim = ? WHERE user_id = ?", (today_str, user_id))
                    else:
                        await db.execute("INSERT INTO economy (user_id, balance, last_daily_claim) VALUES (?, ?, ?)", (0, today_str, user_id))
                    await db.commit()
                    msg += f"\n❌ **每日結算：** 昨天玩太久了，沒收獎勵！"
            else:
                msg += "\n✅ 今日已結算。"
            await ctx.send(msg)

    @commands.command()
    async def buy(self, ctx, item: str = None, target: discord.Member = None):
        if not item:
            embed = discord.Embed(title="🛒 曼巴雜貨店", color=0x00ff00)
            embed.add_field(name="`!buy roast @人` (5幣)", value="花錢請機器人罵他。", inline=False)
            embed.add_field(name="`!buy pardon` (20幣)", value="消除今日遊戲紀錄。", inline=False)
            embed.add_field(name="`!buy rename @人` (50幣)", value="幫對方改羞恥暱稱。", inline=False)
            await ctx.send(embed=embed)
            return

        user_id = ctx.author.id
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            balance = row[0] if row else 0

            if item == "roast":
                cost = 5
                if not target or balance < cost:
                    await ctx.send("❌ 錢不夠或沒標記人！")
                    return
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                await db.commit()
                roasts = [f"喂 {target.mention}！有人花錢叫我罵你：你是軟蛋！", f"{target.mention}，如果你把打遊戲的時間拿來練球，早就進 NBA 了！"]
                await ctx.send(random.choice(roasts))

            elif item == "pardon":
                cost = 20
                if balance < cost:
                    await ctx.send("❌ 錢不夠！")
                    return
                today_str = datetime.now().strftime('%Y-%m-%d')
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                await db.execute("DELETE FROM playtime WHERE user_id = ? AND last_played = ?", (user_id, today_str))
                await db.commit()
                await ctx.send(f"💸 {ctx.author.mention} 買通了裁判，今日紀錄已銷毀！")

            elif item == "rename":
                cost = 50
                if not target or balance < cost:
                    await ctx.send("❌ 錢不夠或沒標記人！")
                    return
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                await db.commit()
                names = ["我愛打鐵", "我是軟蛋", "20年老替補", "飲水機守護神"]
                try:
                    await target.edit(nick=random.choice(names))
                    await ctx.send(f"💸 交易成功！{target.mention} 被強制改名了！")
                except:
                    await ctx.send("❌ 改名失敗 (權限不足)，但錢已經扣了嘿嘿！")

    # --- 🏀 1 on 1 單挑系統 (新功能) ---
    @commands.command()
    async def duel(self, ctx, target: discord.Member, amount: int):
        if target.bot or target == ctx.author or amount <= 0:
            await ctx.send("❌ 無效的對手或金額！")
            return

        user_id = ctx.author.id
        target_id = target.id

        async with aiosqlite.connect(self.db_name) as db:
            # 檢查雙方餘額
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row or row[0] < amount:
                await ctx.send("❌ 你的錢不夠！")
                return
            
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (target_id,))
            row = await cursor.fetchone()
            if not row or row[0] < amount:
                await ctx.send("❌ 對手太窮了！")
                return

        # 發起挑戰
        await ctx.send(f"🏀 **單挑挑戰書**\n{ctx.author.mention} 挑戰 {target.mention}！賭金 `{amount}` 幣。\n{target.mention} 請輸入 `accept` 接受，或 `refuse` 拒絕。")

        def check(m):
            return m.author == target and m.channel == ctx.channel and m.content.lower() in ['accept', 'refuse']

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=30.0)
            if msg.content.lower() == 'refuse':
                await ctx.send(f"👎 {target.mention} 拒絕了挑戰，全場噓聲！")
                return
            
            await ctx.send("🏀 比賽開始！雙方激烈攻防...")
            await asyncio.sleep(2) # 營造緊張氣氛
            
            s1 = random.randint(0, 100) # 發起者分數
            s2 = random.randint(0, 100) # 對手分數
            while s1 == s2: s1, s2 = random.randint(0, 100), random.randint(0, 100)

            result = f"📊 **{ctx.author.display_name}** {s1} : {s2} **{target.display_name}**\n"
            
            async with aiosqlite.connect(self.db_name) as db:
                if s1 > s2:
                    await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                    await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (amount, target_id))
                    result += f"🏆 **勝者：{ctx.author.mention}**！贏走了 `{amount}` 幣！"
                else:
                    await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                    await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
                    result += f"🏆 **勝者：{target.mention}**！反殺成功，贏走了 `{amount}` 幣！"
                await db.commit()
            
            await ctx.send(result)
        except asyncio.TimeoutError:
            await ctx.send(f"⏳ {target.mention} 遲遲不敢應戰，比賽取消。")

    @commands.command()
    async def rank(self, ctx):
        try:
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute('SELECT user_id, SUM(seconds) as total FROM playtime GROUP BY user_id ORDER BY total DESC LIMIT 10')
                rows = await cursor.fetchall()
                if not rows:
                    await ctx.send("📊 資料庫空空如也！")
                    return
                
                embed = discord.Embed(title="🏆 偷懶排行榜", color=0xffd700)
                text = ""
                for idx, (uid, sec) in enumerate(rows):
                    m = ctx.guild.get_member(uid)
                    name = m.display_name if m else f"用戶({uid})"
                    text += f"{idx+1}. **{name}**: {sec//3600}小時 {(sec%3600)//60}分\n"
                embed.add_field(name="名單", value=text)
                
                if self.active_sessions:
                    playing = [f"• {ctx.guild.get_member(u).display_name} 玩 {d['game']}" for u, d in self.active_sessions.items() if ctx.guild.get_member(u)]
                    if playing: embed.add_field(name="🔴 進行中", value="\n".join(playing), inline=False)
                
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

async def setup(bot):
    await bot.add_cog(Game(bot))

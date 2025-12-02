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
        
        # 針對遊戲的罵人清單
        self.targeted_roasts = {
            "gta": "俠盜獵車手？🚗 這裡不是洛聖都，去努力工作吧！",
            "grand theft auto": "還在 GTA？除了偷車你還會什麼？",
            "nba": "玩 NBA 2K？🏀 手指動得比腳快有什麼用？",
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

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS economy (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, last_daily_claim DATE)')
            await db.commit()

    # --- 遊戲偵測邏輯 (修復發話位置) ---
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

        # 開始新遊戲 (罵人)
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # 找適合的頻道 (優先找聊天頻道)
            target_names = ["chat", "general", "聊天", "公頻", "主頻道"]
            channel = discord.utils.find(lambda c: any(t in c.name.lower() for t in target_names) and c.permissions_for(after.guild.me).send_messages, after.guild.text_channels)
            
            # 找不到就隨便找一個
            if not channel:
                channel = discord.utils.find(lambda c: c.permissions_for(after.guild.me).send_messages, after.guild.text_channels)
            
            if channel:
                game_lower = new_game.lower()
                msg = next((f"{after.mention} {text}" for kw, text in self.targeted_roasts.items() if kw in game_lower), None)
                if not msg:
                    msg = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
                await channel.send(msg)

    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    # --- 💰 經濟指令 (修復 wallet 沒回應) ---
    @commands.command()
    async def wallet(self, ctx):
        try:
            user_id = ctx.author.id
            today_str = datetime.now().strftime('%Y-%m-%d')
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            async with aiosqlite.connect(self.db_name) as db:
                # 確保用戶存在於經濟表
                await db.execute("INSERT OR IGNORE INTO economy (user_id, balance) VALUES (?, 0)", (user_id,))
                await db.commit()

                cursor = await db.execute("SELECT balance, last_daily_claim FROM economy WHERE user_id = ?", (user_id,))
                row = await cursor.fetchone()
                balance = row[0]
                last_claim = row[1]

                msg = f"💰 **{ctx.author.display_name} 的錢包**\n目前餘額：`{balance}` 曼巴幣\n"

                if last_claim != today_str:
                    cursor = await db.execute("SELECT SUM(seconds) FROM playtime WHERE user_id = ? AND last_played = ?", (user_id, yesterday_str))
                    play_row = await cursor.fetchone()
                    yesterday_seconds = play_row[0] if play_row[0] else 0
                    
                    if yesterday_seconds < 3600: # 1小時內
                        new_balance = balance + 10
                        await db.execute("UPDATE economy SET balance = ?, last_daily_claim = ? WHERE user_id = ?", (new_balance, today_str, user_id))
                        msg += f"\n🎁 **每日結算：** 昨天很自律！獎勵 `+10` 幣！"
                    else:
                        await db.execute("UPDATE economy SET last_daily_claim = ? WHERE user_id = ?", (today_str, user_id))
                        msg += f"\n❌ **每日結算：** 昨天玩太久了，沒收獎勵！"
                    await db.commit()
                else:
                    msg += "\n✅ 今日已結算。"
                
                await ctx.send(msg)
        except Exception as e:
            print(f"Wallet error: {e}")
            await ctx.send(f"❌ 錢包壞掉了：`{e}`")

    # --- 🔥 新功能：俄羅斯輪盤 ---
    @commands.command()
    async def roulette(self, ctx, amount: int):
        if amount <= 0: return await ctx.send("❌ 賭注要大於 0！")
        
        user_id = ctx.author.id
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row or row[0] < amount:
                return await ctx.send("❌ 錢不夠，別想賒帳！")

            # 扣除賭金
            await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            
            await ctx.send(f"🔫 **俄羅斯輪盤**\n{ctx.author.mention} 拿起了左輪手槍，賭注 `{amount}` 幣...\n轉動彈倉...喀嚓...")
            await asyncio.sleep(2)

            bullet = random.randint(1, 6)
            if bullet == 6: # 1/6 機率死亡
                await db.commit() # 錢已經扣了，直接歸零或沒收
                await ctx.send(f"💥 **砰！**\n{ctx.author.mention} 倒在了血泊中... 賭金全沒了！(運氣極差)")
                # 如果在語音頻道，踢出去 (有趣懲罰)
                if ctx.author.voice:
                    await ctx.author.move_to(None)
                    await ctx.send("👻 (並且被踢出了語音頻道)")
            else:
                win = int(amount * 2) # 翻倍
                await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (win, user_id))
                await db.commit()
                await ctx.send(f"💨 **喀...沒事！**\n{ctx.author.mention} 活下來了！獲得 `{win}` 曼巴幣！🎉")

    # --- 🦹 新功能：偷竊系統 ---
    @commands.command()
    async def steal(self, ctx, target: discord.Member):
        if target.bot or target == ctx.author: return await ctx.send("❌ 不能偷這個人！")
        
        user_id = ctx.author.id
        target_id = target.id
        cost = 5 # 偷竊手續費/體力值

        async with aiosqlite.connect(self.db_name) as db:
            # 檢查小偷的錢
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row or row[0] < cost:
                return await ctx.send(f"❌ 你連準備犯罪的 `{cost}` 幣都沒有！")
            
            # 檢查受害者的錢
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (target_id,))
            target_row = await cursor.fetchone()
            if not target_row or target_row[0] <= 0:
                return await ctx.send("❌ 這傢伙已經破產了，放過他吧。")

            # 扣除手續費
            await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
            
            success = random.random() < 0.4 # 40% 成功率
            
            if success:
                # 偷走對方 10% ~ 30% 的錢
                steal_amount = int(target_row[0] * random.uniform(0.1, 0.3))
                if steal_amount < 1: steal_amount = 1
                
                await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (steal_amount, user_id))
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (steal_amount, target_id))
                await ctx.send(f"🦹 **偷竊成功！**\n{ctx.author.mention} 從 {target.mention} 口袋摸走了 `{steal_amount}` 曼巴幣！嘿嘿嘿！")
            else:
                # 失敗，罰款 20 幣給對方
                fine = 20
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (fine, user_id))
                await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (fine, target_id))
                await ctx.send(f"👮 **被抓到了！**\n{ctx.author.mention} 手腳不乾淨被警察抓到！賠償 {target.mention} `{fine}` 曼巴幣！丟臉！")
            
            await db.commit()

    # --- 📊 Rank (修復排名卡住) ---
    @commands.command()
    async def rank(self, ctx):
        try:
            async with aiosqlite.connect(self.db_name) as db:
                # 1. 抓取資料庫所有數據
                cursor = await db.execute('SELECT user_id, SUM(seconds) as total FROM playtime GROUP BY user_id')
                rows = await cursor.fetchall()
                
                # 轉成字典方便處理 {user_id: total_seconds}
                stats = {row[0]: row[1] for row in rows}
                
                # 2. 【關鍵修復】把「現在正在玩」的時間加進去
                current_time = time.time()
                for uid, session in self.active_sessions.items():
                    # 計算這場玩了多久
                    session_duration = int(current_time - session['start'])
                    # 加到總時間裡 (如果資料庫沒這個人，預設為 0)
                    if uid in stats:
                        stats[uid] += session_duration
                    else:
                        stats[uid] = session_duration
                
                # 3. 排序 (由大到小)
                sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

                if not sorted_stats:
                    return await ctx.send("📊 資料庫空空如也！")

                embed = discord.Embed(title="🏆 伺服器偷懶排行榜 (即時更新版)", color=0xffd700)
                text = ""
                for idx, (uid, sec) in enumerate(sorted_stats):
                    m = ctx.guild.get_member(uid)
                    name = m.display_name if m else f"用戶({uid})"
                    
                    # 標示誰正在玩
                    status_icon = "🎮" if uid in self.active_sessions else ""
                    
                    text += f"{idx+1}. **{name}** {status_icon}: {sec//3600}小時 {(sec%3600)//60}分\n"
                
                embed.add_field(name="名單", value=text)
                
                # 下方顯示正在玩的詳細資訊
                if self.active_sessions:
                    playing = []
                    for u, d in self.active_sessions.items():
                        m = ctx.guild.get_member(u)
                        if m:
                            curr_min = int(time.time() - d['start']) // 60
                            playing.append(f"• **{m.display_name}** 正在玩 *{d['game']}* (已 {curr_min} 分鐘)")
                    if playing:
                        embed.add_field(name="🔴 正在進行中", value="\n".join(playing), inline=False)
                
                await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Rank Error: {e}")

    # 保留買東西指令 (簡略版，請保留您原本的 buy 代碼，或用我上一篇的)
    @commands.command()
    async def buy(self, ctx, item: str = None, target: discord.Member = None):
         # ... (這裡請貼上上一篇的 buy 指令代碼，如果需要我再貼一次)
         pass

async def setup(bot):
    await bot.add_cog(Game(bot))

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
        
        # 🔥 1. 針對特定遊戲的「地獄級」罵人清單
        self.targeted_roasts = {
            "gta": [
                "還在 GTA？🚗 虛擬的跑車能帶你去哪？現實生活你的駕照考過了嗎？去工作！💢",
                "俠盜獵車手？除了偷車你還會什麼？去偷點時間來唸書吧！警星 ⭐⭐⭐⭐⭐",
                "這裡不是洛聖都！這裡是殘酷的現實！別再做白日夢了！🛑"
            ],
            "nba": [
                "玩 NBA 2K？🏀 你手指動得比腳還快有什麼用？去球場流汗！廢物！",
                "建了個 99 分的球員就以為自己是 Kobe？你的體脂率有 99% 吧？🍔🚫",
                "曼巴精神不是用手把玩出來的！是用血汗練出來的！關掉遊戲！😤"
            ],
            "league of legends": [
                "又在打 LOL？💀 你的心態炸裂了嗎？還是想讓隊友心態炸裂？",
                "別再雷人了！與其在銅牌場掙扎，不如去現實生活爬分！📉🗑️",
                "打野不幫你？現實生活也沒人會幫你！自己強起來好嗎？⚔️"
            ],
            "valorant": [
                "特戰英豪？🔫 槍法再準，現實生活找不到目標有什麼用？",
                "急停射擊練得不錯嘛？那你的學業/工作進度怎麼停在原地？🛑📉",
                "別再當個只會按滑鼠的特務了！去當個對社會有用的人！🤡"
            ],
            "apex": [
                "APEX？🛡️ 你的肝還好嗎？護甲破了可以補，肝壞了只能去投胎！",
                "整天想著當滋崩狗？做人能不能光明磊落一點？👎🐕",
                "落地成盒？你的人生是不是也打算這樣草草結束？快去努力！💀"
            ],
            "原神": [
                "啟動？😱 給我把書桌前的燈啟動！別再抽卡了！",
                "你的人生抽不到保底的！與其養虛擬老婆，不如養活你自己！💸🚫",
                "原石能吃嗎？體力值滿了？你的腦容量滿了嗎？🧠❓"
            ],
            "honkai": [
                "星穹鐵道？🚂 你的未來是不是也要出軌了？快回正軌去！",
                "回合制遊戲？你的人生可沒有回合制，錯過就沒了！⏳⚠️"
            ]
        }
        
        # 🔥 2. 通用的隨機罵人清單 (更多樣、更兇)
        self.default_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡💢",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？你的羞恥心呢？🚮",
            "嗶嗶！裁判！{member} 在玩 **{game}** 惡意犯規！直接驅逐出場！🟥👋",
            "這時候玩 **{game}**？你的競爭對手正在訓練呢！你打算一輩子當輸家嗎？💀📉",
            "⚠️ 警告！偵測到 **{game}** 正在侵蝕 {member} 的大腦！快停止！🛑🧠",
            "哇，{member} 又在虛度光陰玩 **{game}** 了，真是令人感動的墮落啊！👏🤡",
            "你的肝是用鐵做的嗎？還是你的前途是用紙做的？關掉 **{game}**！🔥📄",
            "{member}，你對得起凌晨四點的太陽嗎？你只對得起你的床！💤👎"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS economy (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, last_daily_claim DATE)')
            await db.commit()

    # --- 遊戲偵測邏輯 (隨機多樣化罵人 + 語音突襲) ---
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
            
            # 1. 準備罵人的話 (先找特定遊戲，沒有就用通用的)
            game_lower = new_game.lower()
            roast_content = None
            
            # 檢查關鍵字
            for kw, msgs in self.targeted_roasts.items():
                if kw in game_lower:
                    # 從該遊戲的罵人清單中隨機挑一句
                    roast_content = f"{after.mention} {random.choice(msgs)}"
                    break
            
            # 如果沒有對應的，就用通用的
            if not roast_content:
                roast_content = random.choice(self.default_roasts).format(member=after.mention, game=new_game)

            # 2. 尋找文字頻道
            target_names = ["chat", "general", "聊天", "公頻", "主頻道"]
            text_channel = discord.utils.find(lambda c: any(t in c.name.lower() for t in target_names) and c.permissions_for(after.guild.me).send_messages, after.guild.text_channels)
            if not text_channel:
                text_channel = discord.utils.find(lambda c: c.permissions_for(after.guild.me).send_messages, after.guild.text_channels)
            
            # 3. 🔥【語音突襲】🔥
            if after.voice and after.voice.channel:
                voice_channel = after.voice.channel
                try:
                    if after.guild.voice_client is None:
                        await voice_channel.connect()
                    elif after.guild.voice_client.channel != voice_channel:
                        await after.guild.voice_client.move_to(voice_channel)
                    
                    if text_channel:
                        # TTS 隨機開場白
                        tts_intros = [
                            f"喂！{after.display_name}！我進來是因為你太吵了！",
                            f"抓到了！{after.display_name}！",
                            f"全體注意！{after.display_name} 正在偷懶！",
                            f"嗶嗶！{after.display_name} 犯規！"
                        ]
                        tts_msg = f"{random.choice(tts_intros)} 你在語音裡面玩 {new_game}，以為我不知道嗎？專心一點！"
                        
                        await text_channel.send(tts_msg, tts=True)
                        await text_channel.send(f"🎙️ **語音查哨突襲！**\n{roast_content}")
                except Exception as e:
                    print(f"Voice Raid Error: {e}")
            else:
                if text_channel:
                    await text_channel.send(roast_content)

    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    # --- 💰 經濟指令 ---
    @commands.command()
    async def wallet(self, ctx):
        try:
            user_id = ctx.author.id
            today_str = datetime.now().strftime('%Y-%m-%d')
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            async with aiosqlite.connect(self.db_name) as db:
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
                    
                    if yesterday_seconds < 3600:
                        new_balance = balance + 10
                        await db.execute("UPDATE economy SET balance = ?, last_daily_claim = ? WHERE user_id = ?", (new_balance, today_str, user_id))
                        msg += f"\n🎁 **每日結算：** 昨天很自律！獎勵 `+10` 幣！💪✨"
                    else:
                        await db.execute("UPDATE economy SET last_daily_claim = ? WHERE user_id = ?", (today_str, user_id))
                        msg += f"\n❌ **每日結算：** 昨天玩太久了，沒

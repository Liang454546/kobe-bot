import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import random

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.checked_today = False # 防止 4:00 重複發送
        
        # 正常勵志語錄 (沒人熬夜時發送)
        self.quotes = [
            "你見過凌晨四點的洛杉磯嗎？早安，曼巴們。🏀",
            "每一種負面情緒——壓力、挑戰——都是我崛起的機會。",
            "低頭不是認輸，是要看清自己的路；仰頭不是驕傲，是要看清自己的天空。",
            "休息是為了走更長遠的路，但不是讓你躺在床上滑手機！",
            "今天的努力，是為了明天的奇蹟。"
        ]

        # 憤怒罵人語錄 (抓到有人熬夜時發送)
        self.angry_roasts = [
            "😡 **{mention}**！現在凌晨四點你還亮著燈？你的肝是鐵做的嗎？去睡覺！",
            "🏀 **{mention}**，你以為你在練球嗎？不，你在修仙！給我滾去睡覺！",
            "⚠️ **{mention}** 警告！曼巴精神是用來訓練的，不是用來熬夜打遊戲的！",
            "👀 抓到了！**{mention}** 這麼晚還在線上？明天的精神去哪了？",
            "💀 **{mention}**，你是想挑戰人體極限嗎？快去睡，不然沒收你的鍵盤！"
        ]

        # 啟動定時任務
        self.morning_call.start()

    def cog_unload(self):
        self.morning_call.cancel()

    # 每 60 秒檢查一次時間
    @tasks.loop(seconds=60)
    async def morning_call(self):
        # 設定台灣時區 (UTC+8)
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)

        # 檢查是否為凌晨 04:00
        if now.hour == 4 and now.minute == 0:
            if not self.checked_today:
                await self.send_motivation()
                self.checked_today = True
        else:
            # 過了 4:00 就重置開關，等待明天
            self.checked_today = False

    async def send_motivation(self):
        # 取得第一個文字頻道或系統頻道
        # 這裡假設機器人在第一個伺服器運作 (通常只有一個)
        if not self.bot.guilds:
            return
            
        guild = self.bot.guilds[0]
        channel = guild.system_channel
        
        # 如果沒有系統頻道，找第一個能說話的文字頻道
        if not channel:
            for c in guild.text_channels:
                if c.permissions_for(guild.me).send_messages:
                    channel = c
                    break
        
        if not channel:
            return

        # --- 掃描熬夜仔邏輯 ---
        stay_up_late_members = []
        
        for member in guild.members:
            if member.bot:
                continue
            
            # 判斷標準：狀態不是「離線」 (包含 線上、閒置、請勿打擾)
            # 或者 正在玩遊戲/直播/聽歌
            is_online = member.status != discord.Status.offline
            is_playing = bool(member.activities)

            if is_online or is_playing:
                stay_up_late_members.append(member)

        # --- 決定發送什麼訊息 ---
        if stay_up_late_members:
            # 如果有人熬夜，切換成「憤怒模式」
            target = random.choice(stay_up_late_members) # 隨機抓一個倒楣鬼出來罵
            msg = random.choice(self.angry_roasts).format(mention=target.mention)
            await channel.send(f"🌅 **凌晨四點點名！**\n{msg}")
        else:
            # 如果大家都乖乖睡覺 (都離線)，發送勵志語錄
            quote = random.choice(self.quotes)
            await channel.send(f"🌅 **凌晨四點：**\n{quote}")

    @morning_call.before_loop
    async def before_morning_call(self):
        # 等待機器人準備好再開始迴圈
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Daily(bot))

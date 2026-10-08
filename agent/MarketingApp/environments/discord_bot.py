"""
Discord Bot Ortamı (Environment).

Telegram bot ile aynı mantıkta çalışır:
  - Metin/görsel mesajları alır
  - BaseModel'e iletir  
  - Yanıtları Discord kanalına gönderir

Gereksinimler:
  pip install discord.py
  .env → DISCORD_TOKEN=xxxx

Kullanım:
  main.py'de: await run_discord_bot(token, base_model)
"""

import asyncio
import io
import os
import traceback
from datetime import datetime

try:
    import discord
    from discord.ext import commands
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    print("⚠️ [Discord] discord.py yüklü değil. 'pip install discord.py' ile yükleyin.")

from MarketingApp.environments.kanal_router import KanalMesaji, mesaj_isle, kanal_kaydet


# ─── Bot Değişkenleri ────────────────────────────────────────────────────────

_base_model = None
_bot = None


def init_discord_env(base_model):
    """Discord ortamına bağımlılıkları enjekte eder."""
    global _base_model
    _base_model = base_model
    print("✅ Discord bot ortamı başlatıldı.")


async def run_discord_bot(token: str, base_model=None):
    """
    Discord botunu başlatır ve çalıştırır.
    
    Args:
        token: Discord bot token'ı
        base_model: BaseModel instance (opsiyonel, init_discord_env ile de verilebilir)
    """
    if not DISCORD_AVAILABLE:
        print("❌ [Discord] discord.py yüklü olmadığı için bot başlatılamadı.")
        return

    global _base_model, _bot

    if base_model:
        _base_model = base_model

    if not _base_model:
        raise ValueError("❌ BaseModel atanmadı! init_discord_env() veya run_discord_bot(token, base_model) kullanın.")

    # Bot intents
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    _bot = bot

    # ─── Discord gönderici fonksiyonunu router'a kaydet ──────────────────
    async def discord_gonder(kullanici_id: str, metin: str):
        """Discord kanalına mesaj gönderir."""
        try:
            channel = bot.get_channel(int(kullanici_id))
            if channel:
                parts = [metin[i:i+2000] for i in range(0, len(metin), 2000)]
                for part in parts:
                    await channel.send(part)
        except Exception as e:
            print(f"❌ [Discord] Mesaj gönderilemedi: {e}")

    kanal_kaydet("discord", discord_gonder)

    # ─── Events ──────────────────────────────────────────────────────────

    @bot.event
    async def on_ready():
        print(f"✅ [Discord] Bot giriş yaptı: {bot.user.name} ({bot.user.id})")
        print(f"   Sunucu sayısı: {len(bot.guilds)}")

    @bot.event
    async def on_message(message):
        # Kendine gelen mesajları yoksay
        if message.author == bot.user:
            return

        # Prefix komutlarını işle
        await bot.process_commands(message)

        # Eğer komut değilse normal mesaj olarak işle
        if message.content.startswith("!"):
            return

        channel_id = str(message.channel.id)
        user_text = message.content

        if not user_text and not message.attachments:
            return

        # Görsel kontrolü
        image_bytes = None
        if message.attachments:
            for att in message.attachments:
                if att.content_type and att.content_type.startswith("image/"):
                    image_bytes = await att.read()
                    if not user_text:
                        user_text = "Bu görseli analiz et ve ne olduğunu açıkla."
                    break

        # Mesajı router üzerinden işle
        try:
            async with message.channel.typing():
                mesaj = KanalMesaji(
                    kaynak="discord",
                    kullanici_id=channel_id,
                    metin=user_text,
                    resim_bytes=image_bytes,
                    metadata={
                        "author": str(message.author),
                        "guild": str(message.guild.name) if message.guild else "DM"
                    }
                )

                yanit = await mesaj_isle(mesaj, _base_model)

                # Yanıtları gönder
                sent_something = False

                # 1. Cevap metinleri (öncelikli)
                if yanit.cevap_metinleri:
                    for cevap in yanit.cevap_metinleri:
                        parts = [cevap[i:i+2000] for i in range(0, len(cevap), 2000)]
                        for part in parts:
                            await message.channel.send(f"💬 {part}")
                    sent_something = True

                # 2. Doğrudan çıktılar 
                if yanit.dogrudan_ciktilar:
                    for dt in yanit.dogrudan_ciktilar:
                        parts = [dt[i:i+2000] for i in range(0, len(dt), 2000)]
                        for part in parts:
                            await message.channel.send(f"📠 {part}")
                    sent_something = True

                # 3. Transcript (ses yoksa metin olarak)
                if not sent_something and yanit.metin:
                    parts = [yanit.metin[i:i+2000] for i in range(0, len(yanit.metin), 2000)]
                    for part in parts:
                        await message.channel.send(f"💬 {part}")
                    sent_something = True

                if not sent_something:
                    await message.channel.send("⚠️ Yanıt alınamadı.")

        except Exception as e:
            print(f"❌ [Discord] Mesaj işleme hatası: {e}")
            traceback.print_exc()
            await message.channel.send(f"❌ Hata: {str(e)[:500]}")

    # ─── Komutlar ────────────────────────────────────────────────────────

    @bot.command(name="durum")
    async def status_cmd(ctx):
        """Sistem durumunu gösterir."""
        from MarketingApp.araclar.sistem_araclari import get_system_status
        durum = get_system_status()
        await ctx.send(f"📊 **Sistem Durumu**\n\n{durum}\n\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    @bot.command(name="yardim")
    async def help_cmd(ctx):
        """Yardım mesajı."""
        from MarketingApp.llms import list_submodels
        submodels = list_submodels()
        sm_list = "\n".join([f"• `{name}` — {desc[:60]}..." for name, desc in submodels.items()])
        await ctx.send(
            f"🤖 **Mimar AI — Discord**\n\n"
            f"**Uzman Ajanlar:**\n{sm_list}\n\n"
            f"💡 Doğal dille mesaj yazarak her şeyi yapabilirsiniz!\n"
            f"**Komutlar:** `!durum` `!yardim`"
        )

    # ─── Bot'u çalıştır ──────────────────────────────────────────────────
    print(f"🚀 [Discord] Bot başlatılıyor...")

    try:
        await bot.start(token)
    except discord.LoginFailure:
        print("❌ [Discord] Token geçersiz! .env'deki DISCORD_TOKEN'ı kontrol edin.")
    except Exception as e:
        print(f"❌ [Discord] Başlatma hatası: {e}")


# ─── Test ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not DISCORD_AVAILABLE:
        print("discord.py yüklü değil. Yüklemek için: pip install discord.py")
    else:
        token = os.getenv("DISCORD_TOKEN")
        if token:
            print("🧪 [Discord Test] Token bulundu, bağlanılıyor...")
            asyncio.run(run_discord_bot(token))
        else:
            print("❌ DISCORD_TOKEN .env dosyasında bulunamadı.")

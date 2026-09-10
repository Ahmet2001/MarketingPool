"""
Ana Giriş Noktası (Entry Point).

Bu dosya uygulamanın yapılandırmasını yapar ve ortamı başlatır.
Mantık kodları ilgili katmanlara (llms, araclar, environments) bölünmüştür.
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

# Windows asyncio workaround for Python 3.8+ (prevents 'Event loop is closed' error)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# .env dosyalarini yukle (yerel override varsa onu en son uygula)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.append(_PROJECT_ROOT)


load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env.local"), override=True)
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env.model"), override=True)
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env.secrets"), override=True)

from MarketingApp.llms import BaseModel
from MarketingApp.llms.runtime_config import get_base_model_name, get_model_api_key
from MarketingApp.araclar import BASE_ARACLAR
from MarketingApp.environments.telegram import init_bot_env, run_telegram_bot
from MarketingApp.environments.heartbeat import heartbeat_loop
from MarketingApp.environments.discord_bot import run_discord_bot, init_discord_env
from MarketingApp.environments.terminal import run_terminal_manager


def _has_telegram_token(value: str | None) -> bool:
    """Bos veya ornek olarak birakilmis Telegram tokenlarini pasif sayar."""
    token = (value or "").strip()
    if not token:
        return False

    normalized = token.upper()
    placeholder_markers = ("YOUR_", "CHANGE_ME", "TELEGRAM_TOKEN_HERE", "BURAYA_")
    return not any(marker in normalized for marker in placeholder_markers)


async def _run_telegram_safely(token: str, base_model):
    """Telegram hatasinin terminal ve heartbeat sureclerini kapatmasini engeller."""
    try:
        await run_telegram_bot(token=token)
    except Exception as exc:
        base_model.log_message("sistem", f"Telegram devre disi kaldi: {exc}")
        print(f"⚠️ Telegram baslatilamadi; terminal calismaya devam ediyor: {exc}")


async def main():
    print("🚀 Mimar başlatılıyor...")

    # API anahtarlarını .env'den oku
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    MODEL_API_KEY = get_model_api_key()
    MODEL_NAME = get_base_model_name()

    if not MODEL_API_KEY:
        raise ValueError("❌ LLM API anahtarı bulunamadı!")

    telegram_enabled = _has_telegram_token(TELEGRAM_TOKEN)

    # 1. Orkestratör modeli oluştur
    base_model = BaseModel(api_key=MODEL_API_KEY, model=MODEL_NAME)
    
    base_model.log_message("sistem", "Mimar terminal yonetimi baslatiliyor...")

    # 2. BaseModel'in doğrudan kullandığı minimal araç setini hazırla
    base_arac_map = {func.__name__: func for func in BASE_ARACLAR}

    # 3. Telegram yapilandirildiysa bagimliliklari enjekte et
    if telegram_enabled:
        init_bot_env(
            base_model=base_model,
            genel_araclar=BASE_ARACLAR,
            genel_arac_map=base_arac_map
        )
    else:
        print("ℹ️ Telegram devre disi; terminal sohbeti kullanilabilir.")

    # 4. Arka plan servislerini terminal oturumuyla birlikte calistir
    background_tasks = [
        asyncio.create_task(heartbeat_loop(base_model), name="heartbeat"),
    ]

    if telegram_enabled:
        background_tasks.append(
            asyncio.create_task(_run_telegram_safely(TELEGRAM_TOKEN, base_model), name="telegram")
        )
    
    # Discord opsiyonel — token varsa çalıştır
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    discord_enabled = bool(DISCORD_TOKEN)
    if discord_enabled:
        init_discord_env(base_model)
        background_tasks.append(
            asyncio.create_task(
                run_discord_bot(token=DISCORD_TOKEN, base_model=base_model),
                name="discord",
            )
        )
        print("🎮 Discord bot aktif edildi.")
    else:
        print("ℹ️ Discord devre dışı (DISCORD_TOKEN .env'de bulunamadı).")

    try:
        await run_terminal_manager(
            base_model,
            telegram_enabled=telegram_enabled,
            discord_enabled=discord_enabled,
        )
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nMimar kapatildi.")

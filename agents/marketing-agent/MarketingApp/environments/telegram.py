"""
Telegram Bot Ortamı (Environment).

Bu modül Telegram botunun tüm mantığını içerir.
BaseModel orkestratörü ile konuşarak kullanıcıya hizmet verir.
"""

import asyncio
import io
import os
import json
import wave
import warnings
import tempfile
import traceback
from datetime import datetime

try:
    from pydub import AudioSegment
    _PYDUB_IMPORT_ERROR = None
except ImportError as pydub_import_error:
    AudioSegment = None
    _PYDUB_IMPORT_ERROR = pydub_import_error
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from MarketingApp.llms import list_submodels
from MarketingApp.environments.automation_runtime import (
    release_automation,
    try_acquire_automation,
)
from MarketingApp.araclar.vlm_araclari import register_bot

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Ses sabitleri
RATE         = 24000
SAMPLE_WIDTH = 2
CHANNELS     = 1

# ─── Kalıcı Bellek (Disk) ────────────────────────────────────────────────────
_HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "workspace", "konusma_gecmisi.json"
)
MAX_HISTORY = 30
MAX_CONTEXT_MESSAGES = 10
MAX_CONTEXT_CHARS = 4000


def _normalize_history_messages(messages: list[dict]) -> list[dict]:
    """Gereksiz tekrarları ve ara sistem çıktılarını temizler."""
    normalized = []
    for msg in messages:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if not role or not content:
            continue
        if content.startswith("[Doğrudan Çıktı]:"):
            continue
        if content.startswith("[Sistem:"):
            continue
        if normalized:
            last = normalized[-1]
            if last.get("role") == role and (last.get("content") or "").strip() == content:
                continue
        normalized.append({
            "role": role,
            "content": content,
            "zaman": msg.get("zaman", datetime.now().strftime("%H:%M"))
        })
    return normalized[-MAX_HISTORY:]


def _load_histories() -> dict:
    """Konuşma geçmişini diskten yükler."""
    os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
    if not os.path.exists(_HISTORY_FILE):
        return {}
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # JSON anahtarları string, biz int chat_id kullanıyoruz
        return {int(k): _normalize_history_messages(v) for k, v in raw.items()}
    except Exception:
        return {}


def _save_histories():
    """Konuşma geçmişini diske kaydeder (arka planda, hata olsa bile devam)."""
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(chat_histories, f, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print(f"[Bellek] Geçmiş kaydedilemedi: {e}")

# ─── Hafıza ──────────────────────────────────────────────────────────────────
chat_histories: dict[int, list[dict]] = _load_histories()  # diskten yükle

# Bot bağımlılıkları (main.py tarafından atanır)
_base_model     = None
_genel_araclar  = None
_genel_arac_map = None


def _format_automation_busy_message(snapshot: dict) -> str:
    owner = snapshot.get("owner") or "otomasyon"
    label = snapshot.get("label") or snapshot.get("job_id") or "aktif gorev"
    started_at = snapshot.get("started_at") or ""

    if owner == "heartbeat":
        base = "💓 Heartbeat şu anda çalışıyor."
    else:
        base = "⏳ Şu anda başka bir otomasyon işlemi çalışıyor."

    details = f"\nAktif görev: {label}" if label else ""
    started = f"\nBaşlangıç: {started_at}" if started_at else ""
    return f"{base}{details}{started}\nLütfen biraz sonra tekrar dene."


def init_bot_env(base_model, genel_araclar, genel_arac_map):
    """Bot ortamına gerekli bağımlılıkları enjekte eder."""
    global _base_model, _genel_araclar, _genel_arac_map
    _base_model     = base_model
    _genel_araclar  = genel_araclar
    _genel_arac_map = genel_arac_map
    print("✅ Telegram bot ortamı başlatıldı.")


def build_context(chat_id: int) -> str:
    """Önceki mesajları ve uzun vadeli belleği birleştirerek bağlam oluşturur."""
    from MarketingApp.araclar.bellek_araclari import bellek_oku
    satirlar = []

    # Uzun vadeli belleği başa ekle
    try:
        uzun_bellek = bellek_oku()
        if "Bellek şu an boş" not in uzun_bellek:
            satirlar.append("=== UZUN VADELİ HAFIZA ===")
            satirlar.append(uzun_bellek)
            satirlar.append("")
    except Exception:
        pass

    history = chat_histories.get(chat_id, [])
    meaningful_history = []
    for msg in history:
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if content.startswith("[Doğrudan Çıktı]:"):
            continue
        if content.startswith("[Sistem:"):
            continue
        meaningful_history.append(msg)

    if meaningful_history:
        satirlar.append("=== ÖNCEKI KONUŞMA GEÇMİŞİ ===")
        selected_messages = meaningful_history[-MAX_CONTEXT_MESSAGES:]
        rendered_messages = []
        total_chars = 0
        for msg in reversed(selected_messages):
            role = "Kullanıcı" if msg["role"] == "user" else "Asistan"
            line = f"{role}: {msg['content']}"
            line_len = len(line)
            if rendered_messages and total_chars + line_len > MAX_CONTEXT_CHARS:
                break
            rendered_messages.append(line)
            total_chars += line_len

        for line in reversed(rendered_messages):
            satirlar.append(line)
        satirlar.append("")

    if satirlar:
        satirlar.append("=== ŞİMDİ KULLANICININ YENİ MESAJI ===")
    return "\n".join(satirlar)


def add_to_history(chat_id: int, role: str, content: str):
    """Konuşma geçmişine mesaj ekle ve diske kaydet."""
    content = (content or "").strip()
    if not content:
        return
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
    if chat_histories[chat_id]:
        last_msg = chat_histories[chat_id][-1]
        if last_msg.get("role") == role and (last_msg.get("content") or "").strip() == content:
            return
    chat_histories[chat_id].append({
        "role": role,
        "content": content,
        "zaman": datetime.now().strftime("%H:%M")
    })
    if len(chat_histories[chat_id]) > MAX_HISTORY:
        # Çok uzarsa başından kısalt (%20 buffer bırak)
        chat_histories[chat_id] = chat_histories[chat_id][int(MAX_HISTORY * 0.2):]
    _save_histories()


def pcm_to_ogg(pcm_data: bytes) -> bytes:
    """Raw PCM → OGG Opus dönüşümü."""
    if AudioSegment is None:
        raise RuntimeError(f"pydub kullanılamıyor: {_PYDUB_IMPORT_ERROR}")
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(RATE)
        wf.writeframes(pcm_data)
    wav_buffer.seek(0)
    audio_segment = AudioSegment.from_wav(wav_buffer)
    ogg_buffer = io.BytesIO()
    audio_segment.export(ogg_buffer, format="ogg", codec="libopus")
    ogg_buffer.seek(0)
    return ogg_buffer.read()


import html

async def _send_direct_texts(context, chat_id: int, direct_texts: list):
    """Ekrana doğrudan basılması gereken uzun metinleri gönderir (4096 karakter limitli parçalar halinde)."""
    for dt in direct_texts:
        parts = [dt[i:i+4000] for i in range(0, len(dt), 4000)]
        for idx, part in enumerate(parts):
            prefix = f"📠 <b>Sistem Çıktısı</b> ({idx+1}/{len(parts)}):\n\n" if len(parts) > 1 else "📠 <b>Sistem Çıktısı:</b>\n\n"
            
            # Telegram'ın katı Markdown/HTML parser'ı sık sık çöker. 
            # İçinde kod bloğu (```) varsa en güvenlisi yalın metin atmak veya basit HTML'e çevirmektir.
            safe_text = html.escape(part)
            
            # Basit kod bloklarını desteklemek istersen (isteğe bağlı):
            # safe_text = safe_text.replace("```", "<pre><code>", 1).replace("```", "</code></pre>", 1)
            
            try:
                await context.bot.send_message(chat_id=chat_id, text=prefix + safe_text, parse_mode="HTML")
            except Exception as e:
                # Korumalı gönderim başarısız olursa düz metin gönder
                print(f"⚠️ HTML Parse Error: {e}")
                await context.bot.send_message(chat_id=chat_id, text=part)


async def _send_cevap_metinleri(context, chat_id: int, cevap_metinleri: list):
    """BaseModel'in metinle_cevapla aracıyla gönderdiği metin yanıtlarını Telegram'a yazar."""
    for cevap in cevap_metinleri:
        parts = [cevap[i:i+4000] for i in range(0, len(cevap), 4000)]
        for idx, part in enumerate(parts):
            prefix = f"💬 ({idx+1}/{len(parts)})\n" if len(parts) > 1 else "💬 "
            safe_text = html.escape(part)
            
            try:
                await context.bot.send_message(chat_id=chat_id, text=prefix + safe_text, parse_mode="HTML")
            except Exception as e:
                await context.bot.send_message(chat_id=chat_id, text=prefix + part)


# --- KOMUTLAR ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Merhaba! Ben Mimar AI Asistanım.*\n\n"
        "📝 Yazılı mesaj gönder veya 🎤 sesli mesaj gönder.\n"
        "📸 Fotoğraf gönderirsen analiz edebilirim.\n\n"
        "Kullanılabilir komutlar:\n"
        "/help — tüm yeteneklerimi listeler\n"
        "/status — sistem durumunu gösterir\n"
        "/reset — konuşma geçmişini sıfırlar",
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    submodels = list_submodels()

    araç_listesi = "\n".join([
        "• `terminal_komut_calistir` — Genel tüm işlemler (dosya, imaj, sistem vb.)",
        "• `get_system_status` — Anlık CPU/RAM durumu",
        "• `bellek_yaz/oku/sil` — Bot'un uzun vadeli kalıcı hafızası",
        "• `workspace_yaz/oku` — Geçici çalışma alanı yönetimi",
        "• `web_arama` — DuckDuckGo ile internet araştırması",
        "• `yeni_arac_yaz/arac_kaydet` — Botun kendi kendine toollarını geliştirmesi",
    ])

    submodel_listesi = "\n".join([
        f"• `{name}` — {desc[:80]}..."
        for name, desc in submodels.items()
    ])

    mesaj = (
        "🧠 *Mimar AI Yetkinlikleri*\n\n"
        "🔧 *Araçlarım:*\n" + araç_listesi + "\n\n"
        "🤖 *Uzmanlaşmış Sub-Ajanlarım:*\n" + submodel_listesi + "\n\n"
        "💡 Natural dil ile her şeyi yapabilirim!"
    )
    await update.message.reply_text(mesaj, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from MarketingApp.araclar.sistem_araclari import get_system_status
    durum = get_system_status()
    chat_id = update.effective_chat.id
    gecmis_sayisi = len(chat_histories.get(chat_id, []))
    submodel_sayisi = len(list_submodels())

    await update.message.reply_text(
        f"📊 *Sistem Durumu*\n\n"
        f"{durum}\n\n"
        f"🗣️ Konuşma geçmişi: {gecmis_sayisi} mesaj\n"
        f"🤖 Aktif SubModel sayısı: {submodel_sayisi}\n"
        f"🕐 Sunucu saati: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode="Markdown"
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in chat_histories:
        del chat_histories[chat_id]
        _save_histories()
    await update.message.reply_text(
        "🔄 Konuşma geçmişi sıfırlandı. Yeni bir konuşma başlatabiliriz!"
    )


# --- MESAJ HANDLER'LARI ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id   = update.effective_chat.id
    register_bot(context.bot, chat_id)
    acquired_runtime = False

    acquired_runtime, snapshot = await try_acquire_automation(
        "telegram",
        job_id=f"telegram-text-{chat_id}",
        label="Telegram metin istegi",
        source="telegram",
    )
    if not acquired_runtime:
        await context.bot.send_message(chat_id=chat_id, text=_format_automation_busy_message(snapshot))
        return

    try:
        add_to_history(chat_id, "user", user_text)

        # Anlık metin gönderimi için yerel callback'ler
        async def send_direct_text_cb(metin: str):
            await _send_direct_texts(context, chat_id, [metin])

        async def send_cevap_metni_cb(cevap: str):
            await _send_cevap_metinleri(context, chat_id, [cevap])

        ctx = build_context(chat_id)
        audio_pcm, transcript, direct_texts, cevap_metinleri = await _base_model.text_query(
            user_text, context=ctx,
            on_direct_text=send_direct_text_cb,
            on_cevap_metni=send_cevap_metni_cb
        )

        if transcript:
            add_to_history(chat_id, "assistant", transcript)

        # Eğer callback'ler çalıştıysa (cevap_metinleri doluysa) ses veya ek metin atma
        if not cevap_metinleri:
            if audio_pcm:
                if AudioSegment is None:
                    fallback = transcript or "Ses yanıtı üretildi ama ses dönüştürücü kullanılamıyor."
                    await context.bot.send_message(chat_id=chat_id, text=f"💬 {fallback}")
                else:
                    ogg_data = pcm_to_ogg(audio_pcm)
                    caption = f"📝 {transcript}" if transcript else None
                    if caption and len(caption) > 1020:
                        caption = caption[:1017] + "..."
                    await context.bot.send_voice(
                        chat_id=chat_id,
                        voice=io.BytesIO(ogg_data),
                        caption=caption
                    )
            elif transcript:
                await context.bot.send_message(chat_id=chat_id, text=f"💬 {transcript}")
            else:
                if not direct_texts:
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ Yanıt alınamadı.")
                else:
                    add_to_history(chat_id, "assistant", "[Sistem: Asistan görevleri çalıştırdı ancak ekstra bir geri bildirim metni üretmedi.]")
                    await context.bot.send_message(chat_id=chat_id, text="⚙️ *İşlemler tamamlandı.* (Asistan ek bir metin mesajı dönmedi)", parse_mode="Markdown")

    except Exception as e:
        print(f"\n❌ [TEXT HATA]: {e}")
        traceback.print_exc()
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Hata oluştu: {str(e)[:500]}")
    finally:
        if acquired_runtime:
            await release_automation("telegram", job_id=f"telegram-text-{chat_id}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    register_bot(context.bot, chat_id)
    acquired_runtime = False

    acquired_runtime, snapshot = await try_acquire_automation(
        "telegram",
        job_id=f"telegram-voice-{chat_id}",
        label="Telegram ses istegi",
        source="telegram",
    )
    if not acquired_runtime:
        await context.bot.send_message(chat_id=chat_id, text=_format_automation_busy_message(snapshot))
        return

    await context.bot.send_message(chat_id=chat_id, text="🎤 Sesli mesajınız işleniyor...")

    try:
        if AudioSegment is None:
            raise RuntimeError(f"pydub kullanılamıyor: {_PYDUB_IMPORT_ERROR}")

        voice_file = await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
            await voice_file.download_to_drive(tmp_path)

        audio = AudioSegment.from_ogg(tmp_path)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        pcm_data = audio.raw_data
        os.unlink(tmp_path)

        add_to_history(chat_id, "user", "[sesli mesaj gönderildi]")
        await context.bot.send_message(chat_id=chat_id, text="🔄 Ses Gemini'ye iletiliyor...")

        # Anlık metin gönderimi için yerel callback'ler
        async def send_direct_text_cb(metin: str):
            await _send_direct_texts(context, chat_id, [metin])

        async def send_cevap_metni_cb(cevap: str):
            await _send_cevap_metinleri(context, chat_id, [cevap])

        ctx = build_context(chat_id)
        audio_pcm, transcript, direct_texts, cevap_metinleri = await _base_model.audio_query(
            pcm_data, context=ctx,
            on_direct_text=send_direct_text_cb,
            on_cevap_metni=send_cevap_metni_cb
        )

        if transcript:
            add_to_history(chat_id, "assistant", transcript)

        if not cevap_metinleri:
            if audio_pcm:
                if AudioSegment is None:
                    fallback = transcript or "Ses yanıtı üretildi ama ses dönüştürücü kullanılamıyor."
                    await context.bot.send_message(chat_id=chat_id, text=f"💬 {fallback}")
                else:
                    ogg_data = pcm_to_ogg(audio_pcm)
                    caption = f"📝 {transcript}" if transcript else None
                    if caption and len(caption) > 1020:
                        caption = caption[:1017] + "..."
                    await context.bot.send_voice(
                        chat_id=chat_id,
                        voice=io.BytesIO(ogg_data),
                        caption=caption
                    )
            elif transcript:
                await context.bot.send_message(chat_id=chat_id, text=f"💬 {transcript}")
            else:
                await context.bot.send_message(chat_id=chat_id, text="⚠️ Ses yanıtı alınamadı.")

    except Exception as e:
        print(f"\n❌ [VOICE HATA]: {e}")
        traceback.print_exc()
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Ses işleme hatası: {str(e)[:500]}")
    finally:
        if acquired_runtime:
            await release_automation("telegram", job_id=f"telegram-voice-{chat_id}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcının gönderdiği fotoğrafı geçici klasöre kaydeder ve analiz isteği oluşturur."""
    chat_id = update.effective_chat.id
    register_bot(context.bot, chat_id)
    caption = update.message.caption or "Bu görseli analiz et ve ne olduğunu açıkla."
    acquired_runtime = False

    acquired_runtime, snapshot = await try_acquire_automation(
        "telegram",
        job_id=f"telegram-photo-{chat_id}",
        label="Telegram gorsel istegi",
        source="telegram",
    )
    if not acquired_runtime:
        await context.bot.send_message(chat_id=chat_id, text=_format_automation_busy_message(snapshot))
        return

    await context.bot.send_message(chat_id=chat_id, text="📸 Fotoğraf alındı, analiz ediliyor...")

    try:
        # En yüksek çözünürlüklü fotoğrafı al
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
            await photo_file.download_to_drive(tmp_path)

        # Anlık metin gönderimi için yerel callback'ler
        async def send_direct_text_cb(metin: str):
            await _send_direct_texts(context, chat_id, [metin])

        async def send_cevap_metni_cb(cevap: str):
            await _send_cevap_metinleri(context, chat_id, [cevap])

        with open(tmp_path, "rb") as f:
            image_bytes = f.read()

        user_text = caption
        add_to_history(chat_id, "user", f"[fotoğraf gönderildi] {caption}")

        ctx = build_context(chat_id)
        audio_pcm, transcript, direct_texts, cevap_metinleri = await _base_model.text_query(
            user_text, context=ctx,
            image_bytes=image_bytes,
            on_direct_text=send_direct_text_cb,
            on_cevap_metni=send_cevap_metni_cb
        )

        if transcript:
            add_to_history(chat_id, "assistant", transcript)

        if cevap_metinleri:
            pass
        elif audio_pcm:
            if AudioSegment is None:
                fallback = transcript or "Ses yanıtı üretildi ama ses dönüştürücü kullanılamıyor."
                await context.bot.send_message(chat_id=chat_id, text=f"💬 {fallback}")
            else:
                ogg_data = pcm_to_ogg(audio_pcm)
                caption_resp = f"📝 {transcript}" if transcript else None
                if caption_resp and len(caption_resp) > 1020:
                    caption_resp = caption_resp[:1017] + "..."
                await context.bot.send_voice(chat_id=chat_id, voice=io.BytesIO(ogg_data), caption=caption_resp)
        elif transcript:
            await context.bot.send_message(chat_id=chat_id, text=f"💬 {transcript}")

    except Exception as e:
        print(f"\n❌ [PHOTO HATA]: {e}")
        traceback.print_exc()
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Fotoğraf işleme hatası: {str(e)[:500]}")
    finally:
        if acquired_runtime:
            await release_automation("telegram", job_id=f"telegram-photo-{chat_id}")
        if "tmp_path" in locals() and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    print(f"\n🔴 [GLOBAL HATA]: {context.error}")
    traceback.print_exception(type(context.error), context.error, context.error.__traceback__)


async def run_telegram_bot(token: str):
    """Telegram botunu başlatır (Async)."""
    if not _base_model:
        raise ValueError("Lütfen önce init_bot_env() ile bağımlılıkları yükleyin.")

    print("🚀 Telegram Botu Başlatılıyor...")
    print(f"🔧 Genel Araç Sayısı: {len(_genel_araclar)}")

    submodels = list_submodels()
    for name, desc in submodels.items():
        print(f"🤖 SubModel [{name}]: {desc[:80]}...")

    app = ApplicationBuilder().token(token).build()

    # Komut handler'ları
    app.add_handler(CommandHandler("start",  start_command))
    app.add_handler(CommandHandler("help",   help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("reset",  reset_command))

    # Mesaj handler'ları
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    app.add_error_handler(error_handler)

    print("✅ Bot çalışıyor! Komutlar: /start /help /status /reset")
    
    # Async polling
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        # Sonsuz döngü: Botu aktif tut
        while True:
            await asyncio.sleep(3600)

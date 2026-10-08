"""
Kanal Router — Kanal-Agnostik Mesaj Yönlendiricisi.

Tüm iletişim kanallarını (Telegram, Discord, vb.) 
tek bir arayüz üzerinden BaseModel'e bağlar.

Her kanal kendi handler'ını yazar, ama mesajları bu router üzerinden
ortak bir formatta BaseModel'e iletir.
"""

from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
from datetime import datetime


@dataclass
class KanalMesaji:
    """Kanal-agnostik mesaj yapısı."""
    kaynak: str           # "telegram", "discord", "whatsapp", vb.
    kullanici_id: str     # Kaynağa özgü kullanıcı ID'si
    metin: str            # Kullanıcının gönderdiği metin
    resim_bytes: Optional[bytes] = None   # Opsiyonel görsel
    ses_bytes: Optional[bytes] = None     # Opsiyonel ses
    zaman: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    metadata: dict = field(default_factory=dict)  # Kanala özgü ekstra veri


@dataclass
class KanalYaniti:
    """BaseModel'den gelen yanıtın kanal-agnostik temsili."""
    metin: Optional[str] = None
    ses_bytes: Optional[bytes] = None
    dogrudan_ciktilar: list = field(default_factory=list)
    cevap_metinleri: list = field(default_factory=list)


# ─── Kayıtlı Kanallar ───────────────────────────────────────────────────────

_kanal_göndericiler: dict[str, Callable] = {}


def kanal_kaydet(kanal_adi: str, gonderici: Callable[[str, str], Awaitable[None]]):
    """
    Bir kanalın yanıt gönderme fonksiyonunu kayıt eder.
    
    Args:
        kanal_adi: "telegram", "discord", vb.
        gonderici: async def send(kullanici_id, metin) fonksiyonu
    """
    _kanal_göndericiler[kanal_adi] = gonderici
    print(f"📡 [Router] '{kanal_adi}' kanalı kayıt edildi.")


async def mesaj_isle(mesaj: KanalMesaji, base_model) -> KanalYaniti:
    """
    Gelen mesajı BaseModel'e iletir ve yanıtı kanal-agnostik formatta döner.
    
    Args:
        mesaj: KanalMesaji instance
        base_model: BaseModel instance
    
    Returns:
        KanalYaniti
    """
    collected_direct = []
    collected_cevap = []

    async def on_direct(text):
        collected_direct.append(text)

    async def on_cevap(text):
        collected_cevap.append(text)

    if mesaj.ses_bytes:
        audio_pcm, transcript, direct_texts, cevap_metinleri = await base_model.audio_query(
            mesaj.ses_bytes,
            on_direct_text=on_direct,
            on_cevap_metni=on_cevap
        )
    else:
        audio_pcm, transcript, direct_texts, cevap_metinleri = await base_model.text_query(
            mesaj.metin,
            image_bytes=mesaj.resim_bytes,
            on_direct_text=on_direct,
            on_cevap_metni=on_cevap
        )

    return KanalYaniti(
        metin=transcript,
        ses_bytes=audio_pcm if audio_pcm else None,
        dogrudan_ciktilar=direct_texts + collected_direct,
        cevap_metinleri=cevap_metinleri + collected_cevap
    )


def kayitli_kanallar() -> list[str]:
    """Kayıtlı kanal isimlerini döner."""
    return list(_kanal_göndericiler.keys())

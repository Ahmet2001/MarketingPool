"""
YouTube kullanim rehberi skill'i.

Bu skill, ajanin YouTube uzerinde arama, kanal/video inceleme,
beğeni ve abonelik gibi aksiyonlarda daha tutarli davranmasi icin
kisa operasyon rehberleri dondurur.
"""

from __future__ import annotations

import re


_COMMON_RULES = """
ORTAK KURALLAR
- Once yuksek seviyeli YouTube araclarini kullan: launch_social_browser, open_social_page, search_youtube_videos, inspect_youtube_channel, inspect_youtube_video, like_youtube_video, subscribe_youtube_channel.
- Video veya kanal baglamini okumadan etkileşim verme.
- YouTube tarafinda daha ogretici ve sakin ton dusun; agresif hype dilinden kacin.
- Aksiyon sonrasi buton durumu veya sayfa sinyalini kontrol et; basariyi varsayma.
"""


_GUIDES = {
    "genel": """
GENEL YOUTUBE AKISI
1. Arama veya inceleme amacini netlestir.
2. search_youtube_videos ya da inspect araci ile baglami topla.
3. Etkileşim gerekiyorsa hedef videoyu veya kanali dogrula.
4. Sonucu not et ve gereksiz tekrar aksiyonundan kacin.
""",
    "video": """
VIDEO ETKILESIMI
1. inspect_youtube_video ile baslik, kanal ve aciklamayi oku.
2. Icerik nise uyuyorsa like_youtube_video kullan.
3. Alakasiz veya dusuk kaliteli icerikte sirf gorunurluk icin etkileşim verme.
""",
    "kanal": """
KANAL INCELEME
1. inspect_youtube_channel ile kanal adi, abone sinyali ve tanimi oku.
2. Uzun vadeli uyum varsa subscribe_youtube_channel dusun.
3. Her kanala otomatik abone olma.
""",
    "recovery": """
HATA SONRASI TOPARLAMA
1. Video veya kanal sayfasinin acik oldugunu yeniden teyit et.
2. Buton durumu degisti mi bak.
3. Belirsizse ayni butona spam tiklama yapma.
"""
}


def _normalize_topic(value: str) -> str:
    text = re.sub(r"[^a-z0-9_ -]+", " ", (value or "").strip().lower())
    if any(token in text for token in ("video", "watch", "like")):
        return "video"
    if any(token in text for token in ("kanal", "channel", "subscribe", "abone")):
        return "kanal"
    if any(token in text for token in ("recovery", "hata", "retry")):
        return "recovery"
    return "genel"


def youtube_kullanim_rehberi(senaryo: str = "genel") -> str:
    """
    YouTube uzerinde nasil hareket edilmesi gerektigini anlatan operasyon rehberi.

    Args:
        senaryo: 'genel', 'video', 'kanal' veya 'recovery'.
    """
    topic = _normalize_topic(senaryo)
    guide = _GUIDES.get(topic, _GUIDES["genel"]).strip()
    return f"# YouTube Kullanim Rehberi ({topic})\n\n{guide}\n\n{_COMMON_RULES.strip()}"

"""
Instagram kullanim rehberi skill'i.

Bu skill, ajanin Instagram uzerinde profil inceleme, post inceleme,
yorum birakma ve takip/like gibi aksiyonlarda daha tutarli ilerlemesi
icin kisa operasyon rehberleri dondurur.
"""

from __future__ import annotations

import re


_COMMON_RULES = """
ORTAK KURALLAR
- Instagram'da once yuksek seviyeli araclari kullan: launch_social_browser, open_social_page, inspect_instagram_profile, inspect_instagram_post, like_instagram_post, follow_instagram_account, comment_instagram_post.
- Browser sosyal otomasyonda gorunur modda acilir; ekrandaki modali, login duvarini veya acik composer'i gormeden aksiyon alma.
- Yorum veya etkileşim yapmadan once postun baglamini oku; alakasiz, spam veya cekilis odakli gonderilerde bos etkileşim verme.
- Ayni hesaba veya ayni gonderiye kopya yorumlar birakma.
- Login duvari, challenge, telefon/email dogrulamasi veya rate-limit belirtisi varsa zorlamayi kes ve raporla.
"""


_GUIDES = {
    "genel": """
GENEL INSTAGRAM AKISI
1. Tarayicinin acik ve oturumun hazir oldugunu dogrula.
2. Hedef hesap veya postu once inspect araci ile oku.
3. Aksiyon sonrasi sayfanin gercekten guncellendigini kontrol et.
4. Gerekirse ayni akisi kisa not olarak workspace'e yaz.
""",
    "profil": """
PROFIL INCELEME
1. inspect_instagram_profile ile bio, isim ve gorunur istatistikleri oku.
2. Hesap crypto/web3 nisine uyuyor mu bak.
3. Gecici hype, spam ya da bot izleri varsa takip etme.
""",
    "post": """
POST ETKILESIMI
1. Once inspect_instagram_post ile caption ve baglami oku.
2. Hafif temas gerekiyorsa like_instagram_post kullan.
3. Gercek bir sohbet firsati varsa comment_instagram_post ile kisa ve dogal yorum birak.
4. Tek cümlelik, postun icine baglanan yorumlari tercih et.
""",
    "recovery": """
HATA SONRASI TOPARLAMA
1. Sayfayi yeniden oku ve oturumun hala acik oldugunu teyit et.
2. Submit basarili mi, yorum gorundu mu kontrol et.
3. Belirsizlik varsa ayni yorumu ikinci kez basma.
"""
}


def _normalize_topic(value: str) -> str:
    text = re.sub(r"[^a-z0-9_ -]+", " ", (value or "").strip().lower())
    if any(token in text for token in ("profil", "profile", "hesap")):
        return "profil"
    if any(token in text for token in ("post", "yorum", "comment", "like", "follow")):
        return "post"
    if any(token in text for token in ("recovery", "hata", "retry")):
        return "recovery"
    return "genel"


def instagram_kullanim_rehberi(senaryo: str = "genel") -> str:
    """
    Instagram uzerinde nasil hareket edilmesi gerektigini anlatan operasyon rehberi.

    Args:
        senaryo: 'genel', 'profil', 'post' veya 'recovery'.
    """
    topic = _normalize_topic(senaryo)
    guide = _GUIDES.get(topic, _GUIDES["genel"]).strip()
    return f"# Instagram Kullanim Rehberi ({topic})\n\n{guide}\n\n{_COMMON_RULES.strip()}"

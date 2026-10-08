"""
X (Twitter) kullanim rehberi skill'i.

Bu skill, ajanin X uzerinde post atma, reply verme, bildirim kontrolu
ve browser fallback akislarinda daha tutarli davranmasi icin kisa
operasyon rehberleri dondurur.
"""

from __future__ import annotations

import re


_COMMON_RULES = """
ORTAK KURALLAR
- Once yuksek seviyeli X araclarini tercih et: launch_x_browser, open_x_page, snapshot_x_feed, save_x_market_snapshot, search_x_posts, get_x_trends, inspect_x_profile, inspect_x_post, scan_x_notifications, get_x_queue, publish_x_post, publish_x_post_with_media, publish_x_thread, reply_to_x_post, send_x_reply, like_x_post, bookmark_x_post, repost_x_post, follow_x_account, engage_with_x_post.
- Generic browser araclari su anda pasif; login/session recovery disinda low-level DOM araci varsayma.
- Post veya reply atmadan once market_state.md, idea_pool.md ve recent_actions kayitlarini okuyup tekrar kontrolu yap.
- X uzerinde ayni niyet icin art arda iki submit deneme. Her gonderimden sonra dogrulama yap.
- Basariyi varsayma. URL, queue durumu, sayfa metni veya yeni post/reply gorunurlugu ile teyit et.
- Login duvari, captcha, rate limit, challenge veya telefon/email dogrulamasi varsa zorlamayi kes ve durumu raporla.
- Her metin tek ana fikre dayansin. Gereksiz hashtag, emoji ve kopya kalip kullanma.
"""


_GUIDES = {
    "genel": """
GENEL X AKISI
1. Gorev posting/reply/notification/feed ise once ilgili yuksek seviyeli X aracinin olup olmadigina bak.
2. Tarayici durumunu dogrula. Oturum acik degilse `launch_x_browser` ile kontrollu baslat.
3. Aksiyon oncesi kisa baglam oku: market_state, idea_pool, recent_actions.
4. Aksiyon sonrasi sonucu teyit et ve log dus.

NEYE DIKKAT ETMELISIN
- Timeline'da gordugun ilk butona degil, goreve en uygun alana git.
- Modal, compose kutusu veya notification thread acilmadan metin yazmaya kalkma.
- Ayni gorevde context sisirmemek icin gereksiz tam DOM yerine ilgili bolumleri oku.
""",
    "post": """
POST ATMA AKISI
1. Once son aksiyonlari kontrol et; ayni konu, ayni aci veya benzer cumle tekrar etmesin.
2. Gorsel varsa publish_x_post_with_media ile drafti hazirla. Bu arac son Post tusuna basmaz.
3. Draft hazir olduktan sonra submit_current_x_composer ile submit et.
4. Submit sonrasinda verify_current_x_submission ile teyit al; gerekiyorsa resolve_recent_x_status_url ile URL coz.
5. Cok parcali anlatim gerekiyorsa publish_x_thread kullan.
6. Metin 240 karakteri gecmesin. Tek fikirli ve net olsun.
7. Gonderimden sonra basarinin kanitini ara: yeni post gorunuyor mu, URL degisti mi, toast veya timeline teyidi var mi.

POST ICIN HATALI DAVRANISLAR
- Bos compose alanina iki kez submit basmak.
- Link/medya icermeyen bir draft'i "paylasildi" sanmak.
- Tam teyit almadan automation_log'a basari yazmak.
""",
    "reply": """
REPLY AKISI
1. Mumkunse send_x_reply veya reply_to_x_post kullan.
2. Hedef yorumun gercekten secili oldugunu dogrula: queue_id, tweet_url, author veya text preview.
3. Cevap kisa, dogal ve yoruma direkt bagli olsun. Generic tesekkur cümlesi spam gibi duruyorsa kullanma.
4. Reply gonderildikten sonra thread veya queue status uzerinden teyit et.

REPLY ICIN HATALI DAVRANISLAR
- Yorumu tam okumadan alakasiz cevap vermek.
- Ayni kisinin benzer mentionlarina ayni kalibi kopyalamak.
- Birden fazla kullaniciya ayni dakika icinde ayni cümleyi gondermek.
""",
    "notifications": """
NOTIFICATION AKISI
1. scan_x_notifications ve get_x_queue ile yeni mention/reply adaylarini topla.
2. Spam, anlamsiz mention veya bot benzeri icerigi skip et.
3. Gercek soru, yorum veya etkileşim firsati varsa reply uret.
4. Her aksiyonun sonucunu queue status ve recent_actions ile kaydet.

SECIM KURALI
- Soru varsa cevap ver.
- Sahici yorum varsa kisa yanit ver.
- Salt mention veya anlamsiz tek kelime ise gec.
""",
    "feed": """
FEED OKUMA VE FIKIR URETME AKISI
1. snapshot_x_feed, search_x_posts, get_x_trends veya save_x_market_snapshot ile limitli sayida guncel post oku.
2. Tum feed'i modele yigma. Ozet cikar, market_state ve idea_pool dosyalarini guncelle.
3. Sonraki post veya yorum kararini bu ozet uzerinden ver.
4. Ayni topic etrafinda dolansan bile her paylasimda farkli bir aci sec.

HEDEF
- Piyasa modunu anla.
- Hangi coin/web3/NFT/defi temasi gundemde onu cikar.
- Ayrik ama tutarli icerik fikirleri uret.
""",
    "engagement": """
ETKILESIM AKISI
1. Hedef postu inspect_x_post ile hizli kontrol et; alakasiz veya dusuk kaliteli icerige bos etkileşim verme.
2. Hafif temas icin like_x_post veya bookmark_x_post kullan.
3. Daha guclu dagitim gerekiyorsa repost_x_post dusun; ama her gordugun seyi repost etme.
4. Ilgili hesap kaliteli ve ayni niste ise follow_x_account kullan.
5. Birden fazla aksiyon gerekiyorsa engage_with_x_post kullan.

ETKILESIMDE HATA
- Sadece otomatik gorunsun diye herkese ayni aksiyon setini uygulamak.
- Incelemeden follow veya repost basmak.
- Zayif, anlamsiz veya spam gorunumlu hesaplara etkileşim dagitmak.
""",
    "browser": """
BROWSER FALLBACK AKISI
1. Once yuksek seviyeli X araci var mi diye kontrol et; yoksa ancak o zaman low-level browser fallback dusun.
2. Compose, reply box, modal veya notification thread acikligini dogrulamadan type etme.
3. Submit sonrasi ekrani yeniden oku ve ayni aksiyonu korlemesine tekrar etme.

BROWSER ICIN OZEL UYARI
- X arayuzu sik degisir; gorunur metin, aria label ve secili thread baglamini birlikte degerlendir.
- Yan panel, popup veya login sheet aciksa once onu ele al.
""",
    "recovery": """
HATA SONRASI TOPARLAMA
1. Dur ve mevcut sayfayi yeniden oku.
2. Gorevin hangi adiminda kalindigini not et.
3. Draft yazildi ama submit teyidi yoksa once ayni draft'in hala kutuda olup olmadigini kontrol et.
4. Sayfa degismis, modal kapanmis veya thread kaybolmussa ilgili hedefe kontrollu sekilde geri don.
5. Hata tekrar ediyorsa spam click yerine rapor ver ve aksiyonu sonlandir.
""",
}


def _normalize_topic(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("twitter", "x")
    text = re.sub(r"[^a-z0-9_ -]+", " ", text)

    if any(token in text for token in ("post", "tweet", "compose", "paylas")):
        return "post"
    if any(token in text for token in ("reply", "yanit", "yorum", "cevap")):
        return "reply"
    if any(token in text for token in ("notif", "mention", "bildirim", "inbox", "queue")):
        return "notifications"
    if any(token in text for token in ("feed", "timeline", "market", "fikir", "idea")):
        return "feed"
    if any(token in text for token in ("like", "begen", "bookmark", "repost", "follow", "takip", "engage", "etkilesim", "thread")):
        return "engagement"
    if any(token in text for token in ("browser", "dom", "click", "type", "fallback")):
        return "browser"
    if any(token in text for token in ("recovery", "error", "hata", "toparla", "retry")):
        return "recovery"
    return "genel"


def x_kullanim_rehberi(senaryo: str = "genel") -> str:
    """
    X uzerinde nasil hareket edilmesi gerektigini anlatan operasyon rehberi.

    Args:
        senaryo: 'genel', 'post', 'reply', 'notifications', 'feed', 'engagement', 'browser' veya 'recovery'.

    Returns:
        Secilen senaryo icin kisa ama uygulanabilir X kullanim rehberi.
    """
    topic = _normalize_topic(senaryo)
    guide = _GUIDES.get(topic, _GUIDES["genel"]).strip()
    return f"# X Kullanim Rehberi ({topic})\n\n{guide}\n\n{_COMMON_RULES.strip()}"

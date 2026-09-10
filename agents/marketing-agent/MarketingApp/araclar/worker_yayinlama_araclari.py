"""
Worker Yayinlama Araclari — social-media-worker'in `publish_jobs` kuyruguna
sema-uyumlu bir is (job) ekler.

Bu modul, bu ajanin (marketing-agent) `../../schemas/publish_request.schema.json`
sozlesmesine uydugu TEK gercek entegrasyon noktasidir: worker su an sadece
`video.publish` ve `instagram.carousel` aksiyonlarini destekliyor (bkz.
`../../future_work.md` — collect_assets/execute_publish gibi digerleri henuz
planlama asamasinda, gercek bir HTTP capability olarak yok).

Onemli sinirlar:
  - `videoUrl`/`imageUrls` HTTPS URL olmali; bu arac yerel dosya YUKLEMEZ.
    Uretilen medyanin (video_post_olustur_ve_mp4_kaydet,
    html_css_post_olustur_ve_png_kaydet) once erisilebilir bir HTTPS
    adrese barindirilmis olmasi gerekir — barindirma bu ajanin degil,
    "App" katmaninin sorumlulugu (bkz. future_work.md sorumluluk tablosu).
  - Bu araclar SADECE video/carousel yayinlamayi kapsar. Begeni, takip,
    yorum, tweet atma gibi islemler worker'da karsiligi olmadigi icin
    Mimar'in kendi browser tabanli sosyal medya araclarinda (supervised
    local) kalmaya devam eder.
"""

from __future__ import annotations

import os

import requests

_ALLOWED_VIDEO_PLATFORMS = {"instagram", "youtube", "tiktok"}
_SUPABASE_TIMEOUT_SECONDS = 15


def _supabase_config() -> tuple[str, str] | str:
    """(base_url, key) dondurur; eksikse kullanici-okur bir hata metni dondurur."""
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return (
            "❌ Hata: SUPABASE_URL ve SUPABASE_SECRET_KEY tanimli degil. "
            "social-media-worker'in kullandigi ayni Supabase projesine ait "
            "degerleri .env dosyasina ekleyin."
        )
    return url, key


def _is_https_url(value: str) -> bool:
    return bool(value) and value.strip().lower().startswith("https://")


def _insert_publish_job(payload: dict, owner_ref: str = "") -> str:
    config = _supabase_config()
    if isinstance(config, str):
        return config

    base_url, key = config
    body = {"payload": payload}
    if owner_ref:
        body["owner_ref"] = owner_ref

    try:
        response = requests.post(
            f"{base_url}/rest/v1/publish_jobs",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=body,
            timeout=_SUPABASE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        rows = response.json()
        job_id = rows[0].get("id") if isinstance(rows, list) and rows else None
        return (
            f"✅ Yayin isi kuyruga eklendi (job_id={job_id or 'bilinmiyor'}). "
            "social-media-worker bu isi kendi dongusunde alip yayinlayacak; "
            "durumu `publish_jobs` tablosundan (status/results alanlari) takip edin."
        )
    except requests.HTTPError as exc:
        detay = exc.response.text[:500] if exc.response is not None else str(exc)
        return f"❌ Supabase isteği basarisiz: {detay}"
    except Exception as exc:
        return f"❌ Yayin isi eklenemedi: {exc}"


def worker_video_yayinla(
    video_url: str,
    platforms: str,
    baslik: str = "",
    aciklama: str = "",
    caption: str = "",
    gizlilik: str = "private",
    credential_ref: str = "",
) -> str:
    """
    Zaten HTTPS uzerinde barindirilan bir videoyu social-media-worker
    araciligiyla Instagram/YouTube/TikTok'a yayinlamak icin kuyruga bir
    `video.publish` isi ekler. Worker'in kendisi gercekten yayinlar; bu arac
    sadece isi olusturur.

    Args:
        video_url: Videonun HTTPS adresi (yerel dosya yolu KABUL EDILMEZ).
        platforms: Virgulle ayrilmis platform listesi. Gecerli degerler:
            instagram, youtube, tiktok (orn: "instagram,youtube").
        baslik: Video basligi (YouTube icin zorunlu, en fazla 100 karakter).
        aciklama: Uzun aciklama metni (en fazla 5000 karakter).
        caption: Kisa altyazi/caption metni (en fazla 2200 karakter).
        gizlilik: private, unlisted veya public (varsayilan private).
        credential_ref: Coklu-hesap kurulumlarinda hangi hesabin kullanilacagini
            belirten referans (opsiyonel).
    """
    if not _is_https_url(video_url):
        return "❌ Hata: video_url https:// ile baslayan bir adres olmali."

    platform_listesi = [p.strip().lower() for p in (platforms or "").split(",") if p.strip()]
    if not platform_listesi:
        return "❌ Hata: en az bir platform belirtin (instagram, youtube, tiktok)."
    gecersiz = [p for p in platform_listesi if p not in _ALLOWED_VIDEO_PLATFORMS]
    if gecersiz:
        return f"❌ Hata: gecersiz platform(lar): {', '.join(gecersiz)}. Izin verilenler: instagram, youtube, tiktok."
    platform_listesi = list(dict.fromkeys(platform_listesi))  # uniqueItems

    if gizlilik not in {"private", "unlisted", "public"}:
        return "❌ Hata: gizlilik 'private', 'unlisted' veya 'public' olmali."
    if "youtube" in platform_listesi and not baslik.strip():
        return "❌ Hata: YouTube icin baslik zorunlu."
    if len(baslik) > 100:
        return "❌ Hata: baslik en fazla 100 karakter olabilir."
    if len(aciklama) > 5000:
        return "❌ Hata: aciklama en fazla 5000 karakter olabilir."
    if len(caption) > 2200:
        return "❌ Hata: caption en fazla 2200 karakter olabilir."

    payload = {
        "action": "video.publish",
        "videoUrl": video_url.strip(),
        "platforms": platform_listesi,
        "privacyStatus": gizlilik,
    }
    if baslik.strip():
        payload["title"] = baslik.strip()
    if aciklama.strip():
        payload["description"] = aciklama.strip()
    if caption.strip():
        payload["caption"] = caption.strip()
    if credential_ref.strip():
        payload["credentialRef"] = credential_ref.strip()

    return _insert_publish_job(payload, owner_ref=credential_ref.strip())


def worker_instagram_carousel_yayinla(
    image_urls: str,
    caption: str = "",
    credential_ref: str = "",
) -> str:
    """
    Zaten HTTPS uzerinde barindirilan 2-10 JPEG gorseli social-media-worker
    araciligiyla Instagram carousel olarak yayinlamak icin kuyruga bir
    `instagram.carousel` isi ekler.

    Args:
        image_urls: Virgulle ayrilmis, https:// ile baslayan 2-10 gorsel
            adresi (orn: "https://cdn.example.com/1.jpg,https://cdn.example.com/2.jpg").
        caption: Carousel altyazisi (en fazla 2200 karakter).
        credential_ref: Coklu-hesap kurulumlarinda hangi hesabin kullanilacagini
            belirten referans (opsiyonel).
    """
    url_listesi = [u.strip() for u in (image_urls or "").split(",") if u.strip()]
    if len(url_listesi) < 2 or len(url_listesi) > 10:
        return "❌ Hata: image_urls 2 ile 10 arasinda https gorsel adresi icermeli."
    gecersiz = [u for u in url_listesi if not _is_https_url(u)]
    if gecersiz:
        return f"❌ Hata: https:// ile baslamayan adres(ler): {', '.join(gecersiz)}"
    if len(caption) > 2200:
        return "❌ Hata: caption en fazla 2200 karakter olabilir."

    payload = {
        "action": "instagram.carousel",
        "imageUrls": url_listesi,
    }
    if caption.strip():
        payload["caption"] = caption.strip()
    if credential_ref.strip():
        payload["credentialRef"] = credential_ref.strip()

    return _insert_publish_job(payload, owner_ref=credential_ref.strip())

"""
Playground (Workspace) Araçları — Ajanın karmaşık görevlerde kullanacağı çalışma alanı.
Büyük veri analizlerinde (örn. 100 mail), çok adımlı görevlerde ara sonuçları
dosyalara kaydetmek ve parça parça okumak için kullan.
"""

import os
import re
from datetime import datetime

from MarketingApp.paths import WORKSPACE_DIR as _WORKSPACE_DIR

# Workspace dizini (varsayilan: proje kok dizini; MIMAR_WORKSPACE_DIR ile override edilebilir)
WORKSPACE_DIR = str(_WORKSPACE_DIR)


def _ensure_workspace():
    """Workspace dizininin var olduğundan emin olur."""
    os.makedirs(WORKSPACE_DIR, exist_ok=True)


def _resolve_workspace_path(dosya_adi: str) -> tuple[str | None, str]:
    """Workspace disina hicbir sekilde cikilamayan guvenli yol cozumler.

    Yalnizca '..' alt dizesini reddetmek, sembolik link tabanli kacislari veya
    normpath sonrasi kalan kose durumlarini yakalamaz; bu yuzden nihai yol
    gercek (realpath) workspace kokunun altinda olmadigi surece reddedilir.
    """
    raw = str(dosya_adi or "").strip()
    if not raw:
        return None, "❌ Hata: Dosya adı boş olamaz."

    candidate = raw.replace("\\", "/").lstrip("/")
    filepath = os.path.normpath(os.path.join(WORKSPACE_DIR, candidate))

    real_workspace = os.path.realpath(WORKSPACE_DIR)
    real_target = os.path.realpath(filepath)
    if real_target != real_workspace and not real_target.startswith(real_workspace + os.sep):
        return None, "❌ Hata: Workspace dışına çıkılamaz."

    safe_path = os.path.relpath(filepath, WORKSPACE_DIR)
    return safe_path, filepath


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_text_file(filepath: str, default: str = "") -> str:
    if not os.path.exists(filepath):
        return default
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def _write_text_file(filepath: str, content: str):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def _clean_inline(value: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[... kırpıldı ...]"


def _tail_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return "[... başı kırpıldı ...]\n" + text[-limit:].lstrip()


def _append_rotating_markdown(dosya_adi: str, title: str, entry: str, max_entries: int = 120):
    safe_path, filepath_or_error = _resolve_workspace_path(dosya_adi)
    if safe_path is None:
        raise ValueError(filepath_or_error)

    filepath = filepath_or_error
    existing = _read_text_file(filepath, f"# {title}\n")
    if not existing.strip():
        existing = f"# {title}\n"

    combined = existing.rstrip() + "\n\n" + entry.strip() + "\n"
    parts = re.split(r"(?m)^##\s+", combined)
    header = _refresh_log_header(parts[0].strip() or f"# {title}", title)
    sections = [part.strip() for part in parts[1:] if part.strip()]

    if len(sections) > max_entries:
        sections = sections[-max_entries:]

    rebuilt = header.rstrip()
    if sections:
        rebuilt += "\n\n" + "\n\n".join(f"## {section}" for section in sections)
    rebuilt += "\n"
    _write_text_file(filepath, rebuilt)


def _refresh_log_header(header: str, title: str) -> str:
    lines = [line.rstrip() for line in (header or "").splitlines() if line.strip()]
    if not lines or not lines[0].startswith("#"):
        lines.insert(0, f"# {title}")

    now = _now_iso()
    cleaned = []
    updated = False
    stale_recent_keys = ("- action_taken:", "- reason:")
    stale_audit_keys = ("- timestamp:", "- event:", "- status:", "- note:")

    for line in lines:
        normalized = line.strip().lower()
        if normalized.startswith("- last_updated:"):
            if not updated:
                cleaned.append(f"- last_updated: {now}")
                updated = True
            continue
        if title == "Recent Actions" and normalized.startswith(stale_recent_keys):
            continue
        if title == "Automation Log" and normalized.startswith(stale_audit_keys):
            continue
        cleaned.append(line)

    if not updated:
        insert_at = 1 if cleaned and cleaned[0].startswith("#") else 0
        cleaned.insert(insert_at, f"- last_updated: {now}")

    return "\n".join(cleaned)


def _append_section_note(dosya_adi: str, section_title: str, note: str):
    safe_path, filepath_or_error = _resolve_workspace_path(dosya_adi)
    if safe_path is None:
        raise ValueError(filepath_or_error)

    filepath = filepath_or_error
    existing = _read_text_file(filepath, "")
    if not existing.strip():
        existing = f"# {section_title}\n"

    heading = f"## {section_title}"
    line = f"- {_now_iso()} | {_clean_inline(note, 700)}"
    if heading not in existing:
        existing = existing.rstrip() + f"\n\n{heading}\n{line}\n"
    else:
        existing = existing.rstrip() + f"\n{line}\n"

    _write_text_file(filepath, existing)


def workspace_yaz(dosya_adi: str, icerik: str) -> str:
    """
    Workspace içine bir dosya yazar (mevcut içeriğin üzerine yazar).
    Büyük veri analizlerinde taslak veya ara sonuç kaydetmek için idealdir.

    Args:
        dosya_adi: Dosya adı (örn: 'analiz_sonucu.txt').
        icerik: Yazılacak içerik.
    """
    _ensure_workspace()
    safe_path, filepath_or_error = _resolve_workspace_path(dosya_adi)
    if safe_path is None:
        return filepath_or_error

    filepath = filepath_or_error
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(icerik)
        return f"✅ '{safe_path}' workspace'e kaydedildi ({len(icerik)} karakter)."
    except Exception as e:
        return f"❌ Workspace yazma hatası: {e}"


def workspace_ekle(dosya_adi: str, icerik: str) -> str:
    """
    Workspace içindeki mevcut bir dosyanın SONUNA içerik ekler (append modu).
    100 maili teker teker bir dosyaya biriktirmek gibi işlemlerde kullan.

    Args:
        dosya_adi: Hedef dosya adı.
        icerik: Eklenecek içerik.
    """
    _ensure_workspace()
    safe_path, filepath_or_error = _resolve_workspace_path(dosya_adi)
    if safe_path is None:
        return filepath_or_error

    filepath = filepath_or_error
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(icerik)
        return f"✅ '{safe_path}' dosyasına {len(icerik)} karakter eklendi."
    except Exception as e:
        return f"❌ Workspace ekleme hatası: {e}"


def workspace_oku(dosya_adi: str) -> str:
    """
    Workspace içindeki bir dosyayı okur.
    40.000 karakterden uzunsa ilk 40.000 karakter döndürülür.

    Args:
        dosya_adi: Okunacak dosyanın adı.
    """
    safe_path, filepath_or_error = _resolve_workspace_path(dosya_adi)
    if safe_path is None:
        return filepath_or_error

    filepath = filepath_or_error
    if not os.path.exists(filepath):
        return f"❌ '{safe_path}' workspace içinde bulunamadı."
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            icerik = f.read()
        if len(icerik) > 40000:
            return f"📄 '{safe_path}' (ilk 40.000/{len(icerik)} karakter):\n{icerik[:40000]}\n\n[... devamı kırpıldı ...]"
        return icerik
    except Exception as e:
        return f"❌ Workspace okuma hatası: {e}"


def workspace_sonunu_oku(dosya_adi: str, karakter: int = 6000) -> str:
    """
    Workspace içindeki bir dosyanın son kısmını okur.
    Log, aksiyon geçmişi veya dönen durum dosyalarında context'i küçük tutmak için kullan.

    Args:
        dosya_adi: Okunacak dosyanın adı.
        karakter: Sondan okunacak karakter sayısı.
    """
    safe_path, filepath_or_error = _resolve_workspace_path(dosya_adi)
    if safe_path is None:
        return filepath_or_error

    filepath = filepath_or_error
    if not os.path.exists(filepath):
        return f"❌ '{safe_path}' workspace içinde bulunamadı."

    try:
        karakter = max(200, min(int(karakter), 40000))
    except Exception:
        karakter = 6000

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            icerik = f.read()

        if len(icerik) <= karakter:
            return icerik

        return (
            f"📄 '{safe_path}' (son {karakter}/{len(icerik)} karakter):\n"
            f"[... başı kırpıldı ...]\n{icerik[-karakter:]}"
        )
    except Exception as e:
        return f"❌ Workspace sonunu okuma hatası: {e}"


def context_paketi_oku(karakter_limit: int = 9000, strateji_dahil: bool = False) -> str:
    """
    Agent'ların context şişirmeden çalışması için canlı hafıza paketini okur.
    role.md, social/market_state.md, social/idea_pool.md ve recent_actions sonunu
    tek kompakt metin olarak döndürür. Sosyal medya veya içerik üretim kararlarından
    önce bu aracı kullan.

    Args:
        karakter_limit: Döndürülecek toplam yaklaşık karakter bütçesi.
        strateji_dahil: true ise crypto strateji dosyasını da ekler.
    """
    _ensure_workspace()
    try:
        limit = max(3000, min(int(karakter_limit), 24000))
    except Exception:
        limit = 9000

    role_budget = max(900, int(limit * 0.20))
    state_budget = max(1200, int(limit * 0.22))
    idea_budget = max(1200, int(limit * 0.22))
    actions_budget = max(1400, int(limit * 0.26))
    strategy_budget = max(1200, int(limit * 0.18))

    def read_workspace_part(relative_path: str, budget: int, tail: bool = False) -> str:
        _, filepath = _resolve_workspace_path(relative_path)
        content = _read_text_file(filepath, f"❌ {relative_path} bulunamadı.")
        return _tail_text(content, budget) if tail else _clip_text(content, budget)

    sections = [
        "## Persona / Role\n" + read_workspace_part("role.md", role_budget),
        "## Market State\n" + read_workspace_part("social/market_state.md", state_budget),
        "## Idea Pool\n" + read_workspace_part("social/idea_pool.md", idea_budget),
        "## Recent Actions\n" + read_workspace_part("social/recent_actions.md", actions_budget, tail=True),
    ]

    if strateji_dahil:
        sections.append(
            "## Strategy\n"
            + read_workspace_part("strategies/crypto_x_strategy.md", strategy_budget)
        )

    return "\n\n".join(sections)


def context_aksiyon_kaydet(
    ajan: str,
    eylem: str,
    ozet: str,
    sonuc: str = "",
    platform: str = "",
    konu: str = "",
    url: str = "",
    dosya: str = "",
    fikir_notu: str = "",
    market_notu: str = "",
    context_notu: str = "",
) -> str:
    """
    Agent hareketlerini canlı hafıza dosyalarına standart formatta kaydeder.
    Başarılı/başarısız sosyal medya aksiyonları, içerik üretimleri, PNG çıktıları,
    araştırma bulguları ve önemli kararlar sonrasında bu aracı çağır.

    Güncellenen dosyalar:
    - social/recent_actions.md: tekrarları önlemek için kısa eylem geçmişi
    - social/automation_log.md: audit kaydı
    - social/idea_pool.md: fikir_notu verilirse yeni not
    - social/market_state.md: market_notu verilirse yeni gözlem

    Args:
        ajan: Kaydı düşen ajan adı.
        eylem: Yapılan iş türü, örn. post_published, png_generated.
        ozet: Kısa insan-okur özet.
        sonuc: success, failed, skipped, draft, pending vb.
        platform: X, Instagram, YouTube, content, workspace vb.
        konu: İşlenen ana konu.
        url: İlgili post/profil/kaynak URL'si.
        dosya: Üretilen veya kullanılan yerel dosya yolu.
        fikir_notu: Idea pool'a eklenecek yeni fikir/öğrenim.
        market_notu: Market state'e eklenecek yeni gözlem.
        context_notu: Sonraki agentlar için dikkat notu.
    """
    _ensure_workspace()
    timestamp = _now_iso()

    clean = {
        "ajan": _clean_inline(ajan or "unknown", 80),
        "eylem": _clean_inline(eylem or "action", 120),
        "ozet": _clean_inline(ozet, 900),
        "sonuc": _clean_inline(sonuc or "recorded", 80),
        "platform": _clean_inline(platform, 80),
        "konu": _clean_inline(konu, 160),
        "url": _clean_inline(url, 500),
        "dosya": _clean_inline(dosya, 500),
        "context_notu": _clean_inline(context_notu, 700),
    }

    def optional_line(label: str, value: str) -> list[str]:
        return [f"- {label}: {value}"] if value else []

    recent_entry = "\n".join([
        f"## {timestamp} | {clean['ajan']} | {clean['eylem']}",
        f"- sonuc: {clean['sonuc']}",
        *optional_line("platform", clean["platform"]),
        *optional_line("konu", clean["konu"]),
        f"- ozet: {clean['ozet']}",
        *optional_line("url", clean["url"]),
        *optional_line("dosya", clean["dosya"]),
        *optional_line("context_notu", clean["context_notu"]),
    ])

    audit_entry = "\n".join([
        f"## {timestamp} | {clean['eylem']}",
        f"- agent: {clean['ajan']}",
        f"- result: {clean['sonuc']}",
        *optional_line("platform", clean["platform"]),
        *optional_line("topic", clean["konu"]),
        f"- summary: {clean['ozet']}",
        *optional_line("url", clean["url"]),
        *optional_line("file", clean["dosya"]),
    ])

    try:
        _append_rotating_markdown("social/recent_actions.md", "Recent Actions", recent_entry, max_entries=140)
        _append_rotating_markdown("social/automation_log.md", "Automation Log", audit_entry, max_entries=240)

        if fikir_notu:
            _append_section_note("social/idea_pool.md", "Agent Notes", fikir_notu)
        if market_notu:
            _append_section_note("social/market_state.md", "Agent Observations", market_notu)

        updated = ["social/recent_actions.md", "social/automation_log.md"]
        if fikir_notu:
            updated.append("social/idea_pool.md")
        if market_notu:
            updated.append("social/market_state.md")
        return "✅ Context hafızası güncellendi: " + ", ".join(updated)
    except Exception as e:
        return f"❌ Context hafızası güncellenemedi: {e}"


def workspace_listele() -> str:
    """Workspace içindeki tüm dosyaları boyutlarıyla listeler."""
    _ensure_workspace()
    try:
        files = sorted(os.listdir(WORKSPACE_DIR))
        if not files:
            return "📂 Workspace şu anda boş."
        satirlar = [f"📂 Workspace ({WORKSPACE_DIR}):"]
        for f in files:
            tam_yol  = os.path.join(WORKSPACE_DIR, f)
            boyut    = os.path.getsize(tam_yol)
            boyut_str = f"{boyut} B" if boyut < 1024 else f"{boyut/1024:.1f} KB"
            satirlar.append(f"  📄 {f} ({boyut_str})")
        return "\n".join(satirlar)
    except Exception as e:
        return f"❌ Listeleme hatası: {e}"


def workspace_sil(dosya_adi: str) -> str:
    """
    Workspace içindeki bir dosyayı siler.

    Args:
        dosya_adi: Silinecek dosyanın adı.
    """
    safe_path, filepath_or_error = _resolve_workspace_path(dosya_adi)
    if safe_path is None:
        return filepath_or_error

    filepath = filepath_or_error
    if not os.path.exists(filepath):
        return f"❌ '{safe_path}' workspace'de bulunamadı."
    try:
        os.remove(filepath)
        return f"✅ '{safe_path}' workspace'den silindi."
    except Exception as e:
        return f"❌ Silme hatası: {e}"

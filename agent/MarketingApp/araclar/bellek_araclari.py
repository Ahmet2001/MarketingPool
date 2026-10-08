"""
Bellek Araçları — BaseModel'in kısa ve uzun vadeli hafıza sistemi.

İki katmanlı bellek:
1. Kısa vadeli: Konuşma bağlamı (telegram.py tarafından yönetilir)
2. Uzun vadeli: JSON tabanlı kalıcı hafıza — önemli bilgiler, kullanıcı tercihleri
"""

import os
import json
from datetime import datetime

from MarketingApp.paths import workspace_path

BELLEK_FILE = workspace_path("uzun_vadeli_bellek.json")


def _yukle_bellek() -> dict:
    os.makedirs(os.path.dirname(BELLEK_FILE), exist_ok=True)
    if not os.path.exists(BELLEK_FILE):
        return {"notlar": [], "tercihler": {}, "kisiler": {}, "gorevler": []}
    try:
        with open(BELLEK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"notlar": [], "tercihler": {}, "kisiler": {}, "gorevler": []}


def _kaydet_bellek(data: dict):
    os.makedirs(os.path.dirname(BELLEK_FILE), exist_ok=True)
    with open(BELLEK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def bellek_yaz(kategori: str, anahtar: str, deger: str) -> str:
    """
    Kritik bilgileri uzun vadeli belleğe kaydeder. Bot her zaman hatırlar.
    
    STRATEJİK KULLANIM REHBERİ:
    - 'tercihler': Kullanıcının favorileri, dil seçimi, çalışma saatleri vb.
    - 'kisiler': Müşteri isimleri, iletişim bilgileri, önemli roller.
    - 'notlar': Proje detayları, stratejik planlar, teknik özetler.
    - 'gorevler': Tamamlanması gereken işler veya hatırlatıcılar.

    Örnek: bellek_yaz("tercihler", "ton", "resmi ve ciddi")
    
    Args:
        kategori: Kaydın kategorisi (örn: tercihler, kisiler, notlar, gorevler).
        anahtar: Kaydın anahtar kelimesi (örn: isim, ton).
        deger: Kaydedilecek asıl bilgi.
    """
    data = _yukle_bellek()
    
    if kategori in ("tercihler", "kisiler"):
        # Dict tabanlı kategoriler
        if kategori not in data:
            data[kategori] = {}
        data[kategori][anahtar] = {
            "deger": deger,
            "tarih": datetime.now().isoformat()
        }
    elif kategori in ("notlar", "gorevler"):
        # Liste tabanlı kategoriler
        if kategori not in data:
            data[kategori] = []
        # Aynı anahtar varsa güncelle
        guncellendi = False
        for item in data[kategori]:
            if item.get("anahtar") == anahtar:
                item["deger"] = deger
                item["tarih"] = datetime.now().isoformat()
                guncellendi = True
                break
        if not guncellendi:
            data[kategori].append({
                "anahtar": anahtar,
                "deger": deger,
                "tarih": datetime.now().isoformat()
            })
    else:
        return f"❌ Bilinmeyen kategori: '{kategori}'. Geçerli kategoriler: tercihler, kisiler, notlar, gorevler"

    _kaydet_bellek(data)
    return f"✅ Belleğe kaydedildi → [{kategori}] {anahtar}: {deger}"


def bellek_oku(kategori: str = "", anahtar: str = "") -> str:
    """
    Uzun vadeli bellekten bilgi okur. Karar vermeden önce buraya bakmak akıllıcadır.
    
    - 'kategori' ve 'anahtar' verilmezse TÜM bellek yapısını döner.
    - Sadece 'kategori' verilirse o kategorideki tüm kayıtları döner.
    
    Args:
        kategori: Okunacak kategori (isteğe bağlı).
        anahtar: Okunacak spesifik kaydın anahtarı (isteğe bağlı).
    """
    data = _yukle_bellek()
    
    if not any([data.get(k) for k in data]):
        return "🧠 Bellek şu an boş. Önemli bir şey söylersen kaydederim."

    if not kategori:
        # Tüm belleği göster
        satirlar = ["🧠 **Uzun Vadeli Bellek:**\n"]
        for kat, icerik in data.items():
            if not icerik:
                continue
            satirlar.append(f"\n**{kat.upper()}:**")
            if isinstance(icerik, dict):
                for k, v in icerik.items():
                    val = v["deger"] if isinstance(v, dict) else v
                    satirlar.append(f"  • {k}: {val}")
            elif isinstance(icerik, list):
                for item in icerik:
                    if isinstance(item, dict):
                        satirlar.append(f"  • {item.get('anahtar','')}: {item.get('deger','')}")
        return "\n".join(satirlar)
    
    kat_data = data.get(kategori)
    if kat_data is None:
        return f"❌ '{kategori}' kategorisi bulunamadı."
    
    if anahtar:
        if isinstance(kat_data, dict):
            item = kat_data.get(anahtar)
            if item:
                val = item["deger"] if isinstance(item, dict) else item
                return f"🧠 [{kategori}] {anahtar}: {val}"
        elif isinstance(kat_data, list):
            for item in kat_data:
                if item.get("anahtar") == anahtar:
                    return f"🧠 [{kategori}] {anahtar}: {item.get('deger', '')}"
        return f"❌ '{anahtar}' anahtarı '{kategori}' kategorisinde bulunamadı."
    
    # Tüm kategoriyi göster
    satirlar = [f"🧠 **{kategori.upper()}:**"]
    if isinstance(kat_data, dict):
        for k, v in kat_data.items():
            val = v["deger"] if isinstance(v, dict) else v
            satirlar.append(f"  • {k}: {val}")
    elif isinstance(kat_data, list):
        for item in kat_data:
            satirlar.append(f"  • {item.get('anahtar','')}: {item.get('deger','')}")
    return "\n".join(satirlar)


def bellek_sil(kategori: str, anahtar: str) -> str:
    """
    Bellekten belirli bir kaydı siler.

    Args:
        kategori: Silinecek kategorinin adı.
        anahtar: Silinecek kaydın anahtarı.
    """
    data = _yukle_bellek()
    kat_data = data.get(kategori)
    if kat_data is None:
        return f"❌ '{kategori}' kategorisi bulunamadı."
    
    if isinstance(kat_data, dict):
        if anahtar in kat_data:
            del kat_data[anahtar]
            _kaydet_bellek(data)
            return f"✅ [{kategori}] '{anahtar}' bellekten silindi."
    elif isinstance(kat_data, list):
        yeni = [x for x in kat_data if x.get("anahtar") != anahtar]
        if len(yeni) < len(kat_data):
            data[kategori] = yeni
            _kaydet_bellek(data)
            return f"✅ [{kategori}] '{anahtar}' bellekten silindi."
    
    return f"❌ '{anahtar}' anahtarı '{kategori}'de bulunamadı."


def rol_oku() -> str:
    """
    Marketing botunun kişiliğini (Persona) barındıran role.md dosyasını okur.
    Bu dosya ajanın kimliğini, tonunu, kime hitap ettiğini ve yasaklı konuları içerir.
    """
    rol_yolu = workspace_path("role.md")
    if not os.path.exists(rol_yolu):
        return "⚠️ role.md dosyası bulunamadı. Lütfen önce çalışma alanında (.workspace/role.md) bir kimlik tanımlayın."
    try:
        with open(rol_yolu, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"❌ Rol okuma başarısız: {e}"


def rol_guncelle(yeni_icerik: str) -> str:
    """
    Marketing botunun kişiliğini baştan aşağıya veya kısmen günceller.
    Tweet atma stratejisi, yeni yasaklar veya yeni konular eklemek için bu aracı kullanın.
    
    Args:
        yeni_icerik: role.md dosyasının tamamen yeni içeriği (Markdown formatında).
    """
    rol_yolu = workspace_path("role.md")
    os.makedirs(os.path.dirname(rol_yolu), exist_ok=True)
    try:
        with open(rol_yolu, "w", encoding="utf-8") as f:
            f.write(yeni_icerik)
        return "✅ Rol (Persona) başarıyla güncellendi! Yeni rol BaseModel tarafından derhal uygulanacaktır."
    except Exception as e:
        return f"❌ Rol güncelleme başarısız: {e}"


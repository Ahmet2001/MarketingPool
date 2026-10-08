"""
Skill Loader — Dinamik Plugin Sistemi.

OpenClaw tarzı YAML tabanlı skill yönetimi: 
  - `araclar/skills/` dizinindeki .yaml dosyalarını tarar
  - Her skill'i ilgili agent'ın tool listesine runtime'da enjekte eder
  - enable/disable desteği ile sıcak yeniden yapılandırma sağlar

Kullanım:
  - Boot: loaded = load_skills()
  - Runtime: enable_skill("hava_durumu"), disable_skill("hava_durumu")
  - Test: python -m MarketingApp.araclar.skill_loader --list
"""

import os
import importlib
from typing import Optional

try:
    import yaml
    _YAML_IMPORT_ERROR = None
except ImportError as yaml_import_error:
    yaml = None
    _YAML_IMPORT_ERROR = yaml_import_error


# ─── Paths ───────────────────────────────────────────────────────────────────

_SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "skills"
)

# Yüklenen skill'lerin registry'si
_skill_registry: dict[str, dict] = {}


# ─── Skill YAML Yapısı ──────────────────────────────────────────────────────
#
# name: hava_durumu
# description: Anlık hava durumu bilgisi çeker
# enabled: true
# agent: arastirma_agent          # Hangi agent'a ait (veya "base" / "all")
# module: MarketingApp.araclar.hava_araclari   # Python modül yolu
# function: hava_durumu_sorgula                 # Fonksiyon adı
#
# ─────────────────────────────────────────────────────────────────────────────


def _load_single_skill(yaml_path: str) -> Optional[dict]:
    """Tek bir .yaml dosyasını okuyup skill bilgilerini döner."""
    if yaml is None:
        print(f"⚠️ [Skill] PyYAML yüklü değil, skill okunamadı: {_YAML_IMPORT_ERROR}")
        return None
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data, dict):
            print(f"⚠️ [Skill] Geçersiz YAML: {yaml_path}")
            return None

        required = ["name", "module", "function"]
        for key in required:
            if key not in data:
                print(f"⚠️ [Skill] '{key}' alanı eksik: {yaml_path}")
                return None

        return data

    except Exception as e:
        print(f"❌ [Skill] YAML okuma hatası ({yaml_path}): {e}")
        return None


def _import_skill_function(module_path: str, function_name: str):
    """Modülden fonksiyonu dinamik import eder."""
    try:
        mod = importlib.import_module(module_path)
        func = getattr(mod, function_name, None)
        if func is None:
            print(f"⚠️ [Skill] '{function_name}' fonksiyonu '{module_path}' modülünde bulunamadı.")
            return None
        return func
    except ImportError as e:
        print(f"❌ [Skill] Modül import hatası ({module_path}): {e}")
        return None
    except Exception as e:
        print(f"❌ [Skill] Beklenmeyen hata ({module_path}.{function_name}): {e}")
        return None


# ─── Public API ──────────────────────────────────────────────────────────────

def load_skills() -> dict[str, dict]:
    """
    `araclar/skills/` dizinindeki tüm .yaml dosyalarını tarar,
    etkin olanları yükler ve registry'e kaydeder.
    
    Returns:
        {skill_name: {"config": dict, "function": callable, "enabled": bool}}
    """
    global _skill_registry
    _skill_registry = {}

    if yaml is None:
        print(f"⚠️ [Skill Loader] PyYAML yüklü değil, skill sistemi devre dışı: {_YAML_IMPORT_ERROR}")
        return _skill_registry

    # Dizin yoksa oluştur
    os.makedirs(_SKILLS_DIR, exist_ok=True)

    yaml_files = [f for f in os.listdir(_SKILLS_DIR) if f.endswith(".yaml")]

    if not yaml_files:
        print("ℹ️ [Skill] Henüz skill tanımlanmamış (araclar/skills/ boş).")
        return _skill_registry

    for filename in yaml_files:
        filepath = os.path.join(_SKILLS_DIR, filename)
        data = _load_single_skill(filepath)
        if data is None:
            continue

        name = data["name"]
        enabled = data.get("enabled", True)

        if enabled:
            func = _import_skill_function(data["module"], data["function"])
        else:
            func = None

        _skill_registry[name] = {
            "config": data,
            "function": func,
            "enabled": enabled,
            "yaml_path": filepath
        }

        status = "✅ Aktif" if enabled and func else ("⏸️ Devre dışı" if not enabled else "❌ Import hatası")
        agent = data.get("agent", "genel")
        print(f"🧩 [Skill] {name} ({agent}) — {status}")

    print(f"🧩 [Skill Loader] Toplam {len(_skill_registry)} skill yüklendi.")
    return _skill_registry


def get_skills() -> dict[str, dict]:
    """Yüklenmiş tüm skill'leri döner."""
    return _skill_registry


def get_active_skills(agent: str = None) -> list:
    """
    Aktif skill fonksiyonlarını döner.
    
    Args:
        agent: Belirli bir agent için filtrele (None = hepsi)
    
    Returns:
        [callable, ...]
    """
    result = []
    for name, info in _skill_registry.items():
        if not info["enabled"] or info["function"] is None:
            continue
        if agent and info["config"].get("agent") not in (agent, "all", None):
            continue
        result.append(info["function"])
    return result


def enable_skill(name: str) -> bool:
    """Bir skill'i etkinleştirir."""
    if name not in _skill_registry:
        print(f"⚠️ [Skill] '{name}' bulunamadı.")
        return False

    info = _skill_registry[name]
    if info["enabled"]:
        return True  # Zaten aktif

    # Fonksiyonu import et
    data = info["config"]
    func = _import_skill_function(data["module"], data["function"])
    if func is None:
        return False

    info["function"] = func
    info["enabled"] = True

    # YAML'ı güncelle
    data["enabled"] = True
    _save_skill_yaml(info["yaml_path"], data)

    print(f"✅ [Skill] '{name}' etkinleştirildi.")
    return True


def disable_skill(name: str) -> bool:
    """Bir skill'i devre dışı bırakır."""
    if name not in _skill_registry:
        print(f"⚠️ [Skill] '{name}' bulunamadı.")
        return False

    info = _skill_registry[name]
    info["enabled"] = False
    info["function"] = None

    # YAML'ı güncelle
    data = info["config"]
    data["enabled"] = False
    _save_skill_yaml(info["yaml_path"], data)

    print(f"⏸️ [Skill] '{name}' devre dışı bırakıldı.")
    return True


def list_skills() -> list[dict]:
    """Yonetim arayuzleri icin skill listesini döner."""
    return [
        {
            "name": name,
            "description": info["config"].get("description", ""),
            "agent": info["config"].get("agent", "genel"),
            "enabled": info["enabled"],
        }
        for name, info in _skill_registry.items()
    ]


def _save_skill_yaml(filepath: str, data: dict):
    """Güncellenen skill config'ini YAML'a yazar."""
    if yaml is None:
        print(f"❌ [Skill] PyYAML yüklü olmadığı için '{filepath}' yazılamadı.")
        return
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        print(f"❌ [Skill] YAML yazma hatası: {e}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if "--list" in sys.argv:
        skills = load_skills()
        if not skills:
            print("\nHiç skill bulunamadı. 'araclar/skills/' dizinine .yaml dosyaları ekleyin.")
        else:
            print(f"\n{'='*60}")
            print(f"{'İsim':<20} {'Agent':<18} {'Durum':<10}")
            print(f"{'='*60}")
            for name, info in skills.items():
                status = "Aktif" if info["enabled"] else "Devre dışı"
                agent = info["config"].get("agent", "genel")
                print(f"{name:<20} {agent:<18} {status:<10}")
    else:
        print("Kullanım: python -m MarketingApp.araclar.skill_loader --list")

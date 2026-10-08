"""Telegram / Discord icin kullanici yetkilendirmesi (ortam degiskeni tabanli allowlist).

Neden var
---------
Botlarda hic yetki kontrolu yoktu: bota yazabilen HERKES Ethgent'i, dolayisiyla bagli
gercek X hesabini yonlendirebiliyordu. Ayrica terminal komutlari (ajan/tool/heartbeat
yonetimi) botlara tasinacaksa, bunun yalnizca belirli kisilere acik olmasi gerekir.

Iki ayri seviye vardir:

* ``<KANAL>_ALLOWED_USER_IDS``  -- sohbet edebilecek kullanicilar. Tanimli DEGILSE sohbet
  eskisi gibi herkese acik kalir (geriye uyumluluk) ve acilista yuksek sesle uyarilir.
* ``<KANAL>_ADMIN_IDS``         -- yonetim komutlarini calistirabilenler. Tanimli DEGILSE
  yonetim komutlari tamamen kapalidir (yeni ozellik: guvensiz varsayilan yok).

Admin olan kullanici, allowlist tanimli olsa bile sohbet edebilir.
Degerler virgul/bosluk/noktalivirgul ayrimli sayisal kullanici ID'leridir; her cagrida
ortamdan okunur, boylece testler ve yeniden yukleme ortami degistirebilir.
"""

from __future__ import annotations

import os
import re

_PREFIX = {"telegram": "TELEGRAM", "discord": "DISCORD"}


def _prefix(channel: str) -> str:
    try:
        return _PREFIX[channel]
    except KeyError:
        raise ValueError(f"Bilinmeyen kanal: {channel}") from None


def _parse_ids(raw: str | None) -> tuple[set[int], list[str]]:
    ids: set[int] = set()
    invalid: list[str] = []
    for token in re.split(r"[,\s;]+", (raw or "").strip()):
        if not token:
            continue
        try:
            ids.add(int(token))
        except ValueError:
            invalid.append(token)
    return ids, invalid


def allowed_ids(channel: str) -> set[int]:
    return _parse_ids(os.getenv(f"{_prefix(channel)}_ALLOWED_USER_IDS"))[0]


def admin_ids(channel: str) -> set[int]:
    return _parse_ids(os.getenv(f"{_prefix(channel)}_ADMIN_IDS"))[0]


def is_admin(channel: str, user_id: int | None) -> bool:
    return user_id is not None and user_id in admin_ids(channel)


def is_allowed(channel: str, user_id: int | None) -> bool:
    """Sohbet yetkisi. Allowlist tanimli degilse herkese aciktir (geriye uyumluluk)."""
    allowed = allowed_ids(channel)
    if not allowed:
        return True
    return user_id is not None and (user_id in allowed or user_id in admin_ids(channel))


def is_open(channel: str) -> bool:
    return not allowed_ids(channel)


def startup_warnings(channel: str) -> list[str]:
    """Bot acilirken basilacak, yapilandirma durumunu anlatan satirlar."""
    prefix = _prefix(channel)
    warnings: list[str] = []

    for suffix in ("ALLOWED_USER_IDS", "ADMIN_IDS"):
        invalid = _parse_ids(os.getenv(f"{prefix}_{suffix}"))[1]
        if invalid:
            warnings.append(f"{prefix}_{suffix} icinde sayisal olmayan degerler yok sayildi: {', '.join(invalid)}")

    if is_open(channel):
        warnings.append(
            f"{channel.capitalize()} botu HERKESE ACIK: {prefix}_ALLOWED_USER_IDS tanimli degil. "
            "Bota yazan herkes Ethgent'i (ve bagli hesaplari) yonlendirebilir."
        )
    if not admin_ids(channel):
        warnings.append(
            f"{channel.capitalize()} uzaktan yonetim komutlari KAPALI ({prefix}_ADMIN_IDS tanimli degil)."
        )
    return warnings

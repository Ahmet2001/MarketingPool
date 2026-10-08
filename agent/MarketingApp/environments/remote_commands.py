"""Terminal yonetim komutlarini Telegram / Discord uzerinden, guvenli bir alt kume olarak calistirir.

Guvenlik modeli
---------------
Bu modul yetkilendirmeyi KENDISI yapmaz; cagiran (bot handler'i) once ``access.is_admin``
ile kullaniciyi dogrulamalidir. Burada ise "admin bile olsa uzaktan calistirilmamasi"
gereken islemler engellenir:

* ``/tool create|edit|delete``  -- tool kodu sunucuda calisir; uzaktan kod yukleme = uzaktan kod calistirma.
* ``/tool show --code``         -- kaynak kod (icinde gizli bilgi olabilir) sohbet gecmisine duser.
* ``/agent pack ...``           -- dosya sistemi yolu alir.
* ``/agent create --builtin``   -- SubModels/ altina Python dosyasi yazar.
* ``/exit``, ``/clear``, ``/history`` -- terminal oturumuna ozel.

Yikici komutlar (``delete``, ``remove``) uzaktan ``--yes`` ister: onay soracak etkilesimli
bir kanal yoktur, bu yuzden onay komutun kendisinde acikca verilmelidir.
"""

from __future__ import annotations

import os
import re
import shlex

from MarketingApp import telemetry
from MarketingApp.environments.terminal import _AGENT_SWITCH_WORDS, TerminalManager
from MarketingApp.paths import workspace_path

REMOTE_COMMANDS = frozenset(
    {"/agents", "/agent", "/tools", "/tool", "/errors", "/logs", "/runs", "/run", "/usage", "/heartbeat", "/reload"}
)

_MAX_OUTPUT_CHARS = 20000
_NO_CONFIRM = "Uzaktan silme icin komuta --yes ekle (onay soracak etkilesimli kanal yok)."


def normalize_line(text: str) -> str:
    """Mesaj uygulamalarinin 'akilli' duzeltmelerini geri alir.

    iOS/macOS klavyeleri ``--`` yi tire (—/–) yapar, ``"`` yi egri tirnaga cevirir;
    Telegram grup sohbetlerinde komut ``/agent@BotAdi`` seklinde gelir.
    """
    cleaned = (text or "").strip()
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    cleaned = re.sub(r"[\u2013\u2014](?=[A-Za-z])", "--", cleaned)
    return re.sub(r"^(/\w+)@\w+", r"\1", cleaned)


def check_allowed(parts: list[str]) -> str | None:
    """Komut uzaktan calistirilabilir mi? Engel varsa nedenini, yoksa None dondurur."""
    command = parts[0].lower()
    args = parts[1:]
    lowered = [item.lower() for item in args]

    if command not in REMOTE_COMMANDS:
        return f"{command} uzaktan calistirilamaz."

    if command == "/tool":
        if len(args) == 2 and lowered[1] in _AGENT_SWITCH_WORDS:
            return None
        sub = lowered[0] if lowered else ""
        if sub == "list":
            return None
        if sub == "show":
            return "/tool show --code uzaktan kapali (kaynak kod sohbet gecmisine duser)." if "--code" in lowered else None
        return (
            "Tool olusturma/duzenleme/silme uzaktan kapali: tool kodu sunucuda calisir. "
            "Bunu terminalden yap."
        )

    if command == "/agent":
        if not args or (len(args) == 2 and lowered[1] in _AGENT_SWITCH_WORDS):
            return None
        sub = lowered[0]
        if sub == "pack":
            return "Pack islemleri dosya yolu gerektirir; uzaktan kapali."
        if sub == "create" and "--builtin" in lowered:
            return "--builtin uzaktan kapali (SubModels/ altina Python dosyasi yazar)."
        if sub == "delete" and "--yes" not in lowered:
            return _NO_CONFIRM
        return None

    if command == "/heartbeat":
        if lowered and lowered[0] == "remove" and "--yes" not in lowered:
            return _NO_CONFIRM
        return None

    return None


def _deny_input(_prompt: str) -> str:
    """Onay isteyen her yol 'hayir' ile sonuclanir; onay yalnizca --yes ile verilebilir."""
    return ""


async def run_remote_command(base_model, line: str, *, channel: str, actor: int | str | None = None) -> str:
    """Komutu calistirip terminal ciktisini duz metin olarak dondurur. Yetki kontrolu CAGIRANIN isidir."""
    normalized = normalize_line(line)
    try:
        parts = shlex.split(normalized)
    except ValueError as exc:
        return f"Komut okunamadi: {exc}"
    if not parts:
        return ""

    reason = check_allowed(parts)
    telemetry.record_event(
        "remote",
        f"{channel}:{actor} {'REDDEDILDI (' + reason + ')' if reason else 'calistirdi'}: {normalized[:300]}",
    )
    if reason:
        return f"⛔ {reason}"

    lines: list[str] = []
    manager = TerminalManager(
        base_model,
        input_func=_deny_input,
        output_func=lines.append,
        history_file=workspace_path(".system", "remote_commands_unused.json"),
        source=channel,
    )
    try:
        await manager.handle_line(normalized)
    except Exception as exc:  # noqa: BLE001 - kanal thread'ini bozmasin
        lines.append(f"Komut hatasi: {exc}")

    output = "\n".join(lines).strip() or "(cikti yok)"
    if len(output) > _MAX_OUTPUT_CHARS:
        output = output[:_MAX_OUTPUT_CHARS] + "\n... (kisaltildi)"
    return output


def split_message(text: str, limit: int) -> list[str]:
    """Kanalin mesaj sinirina gore, mumkunse satir sinirlarindan bol."""
    chunks: list[str] = []
    current = ""
    for line in (text or "").splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks or [""]

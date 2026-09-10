"""Mimar icin interaktif terminal yonetim arayuzu."""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
import re
import shlex
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from MarketingApp.environments.automation_runtime import (
    get_automation_snapshot,
    release_automation,
    try_acquire_automation,
)
from MarketingApp.environments.heartbeat import (
    HeartbeatConfigError,
    add_task_to_content,
    get_heartbeat_jobs_snapshot,
    get_heartbeat_status_snapshot,
    parse_config_content,
    pause_heartbeat_job,
    read_config_content,
    reload_heartbeat_service,
    remove_task_from_content,
    resume_heartbeat_job,
    run_heartbeat_job,
    set_enabled_in_content,
    write_config_content,
)


from MarketingApp.paths import workspace_path


def _studio():
    """agent_studio'yu tembel yukle; import aninda llms paketini ayaga kaldirmamak icin."""
    from MarketingApp.llms import agent_studio

    return agent_studio


_HISTORY_FILE = workspace_path(".system", "terminal_chat_history.json")
_MAX_HISTORY = 30
_MAX_CONTEXT_MESSAGES = 12
_MAX_CONTEXT_CHARS = 5000
_AGENT_SWITCH_WORDS = {"on", "off", "toggle", "ac", "kapat", "aktif", "pasif", "degistir"}
_AFFIRMATIVE_ANSWERS = {"e", "evet", "y", "yes"}


class TerminalManager:
    """Sohbeti ve temel runtime islemlerini tek terminal dongusunde yonetir."""

    def __init__(
        self,
        base_model,
        *,
        telegram_enabled: bool = False,
        discord_enabled: bool = False,
        input_func: Callable[[str], Any] = input,
        output_func: Callable[[str], Any] = print,
        history_file: str = _HISTORY_FILE,
    ):
        self.base_model = base_model
        self.telegram_enabled = bool(telegram_enabled)
        self.discord_enabled = bool(discord_enabled)
        self.input_func = input_func
        self.output_func = output_func
        self.history_file = history_file
        self.history = self._load_history()
        self._original_request_approval = getattr(base_model, "request_approval", None)
        self._use_color = output_func is print and sys.stdout.isatty() and not os.getenv("NO_COLOR")

    async def run(self) -> None:
        self.base_model.request_approval = self._request_terminal_approval
        self._print_banner()
        try:
            while True:
                try:
                    line = await self._read_line(self._color("sen> ", "cyan"))
                except (EOFError, KeyboardInterrupt):
                    self._emit("\nTerminal oturumu kapatiliyor.")
                    return

                if line is None:
                    return
                if not await self.handle_line(str(line)):
                    return
        finally:
            if self._original_request_approval is not None:
                self.base_model.request_approval = self._original_request_approval

    async def handle_line(self, raw_line: str) -> bool:
        line = (raw_line or "").strip()
        if not line:
            return True
        if line.startswith("/"):
            return await self._handle_command(line)
        await self._chat(line)
        return True

    async def _read_line(self, prompt: str) -> str:
        if self.input_func is input:
            return await asyncio.to_thread(input, prompt)
        result = self.input_func(prompt)
        if inspect.isawaitable(result):
            return await result
        return result

    def _emit(self, message: str = "") -> None:
        self.output_func(str(message))

    def _color(self, text: str, color: str) -> str:
        if not self._use_color:
            return text
        codes = {
            "cyan": "\033[96m",
            "green": "\033[92m",
            "yellow": "\033[93m",
            "red": "\033[91m",
            "bold": "\033[1m",
        }
        return f"{codes.get(color, '')}{text}\033[0m"

    def _print_banner(self) -> None:
        model = getattr(self.base_model, "model", "bilinmiyor")
        provider = getattr(self.base_model, "provider_name", "bilinmiyor")
        self._emit("")
        self._emit(self._color("MIMAR TERMINAL", "bold"))
        self._emit(f"Model: {model} | Saglayici: {provider}")
        self._emit(
            f"Telegram: {'aktif' if self.telegram_enabled else 'kapali'} | "
            f"Discord: {'aktif' if self.discord_enabled else 'kapali'}"
        )
        self._emit("Mesaj yaz veya komutlari gormek icin /help kullan. Cikmak icin /exit.")
        if self.history:
            self._emit(f"Onceki terminal sohbetinden {len(self.history)} mesaj yuklendi.")
        errors = self._studio_errors()
        if errors:
            self._emit(self._color(f"UYARI: {len(errors)} config hatasi var. /errors ile bak.", "yellow"))
        self._emit("")

    async def _handle_command(self, line: str) -> bool:
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            self._emit(self._color(f"Komut okunamadi: {exc}", "red"))
            return True

        command = parts[0].lower()
        args = parts[1:]

        if command in {"/exit", "/quit", "/q"}:
            self._emit("Mimar kapatiliyor...")
            return False
        if command in {"/help", "/?"}:
            self._print_help()
        elif command == "/status":
            self._print_status()
        elif command == "/agents":
            self._print_agents()
        elif command == "/agent":
            await self._manage_agent(args)
        elif command == "/tools":
            self._print_tools(args)
        elif command == "/tool":
            await self._manage_tool(args)
        elif command == "/logs":
            self._print_logs(args)
        elif command == "/errors":
            self._print_errors(args)
        elif command == "/history":
            self._print_history()
        elif command == "/clear":
            self._clear_history()
        elif command == "/reload":
            self._reload_agents()
        elif command == "/heartbeat":
            await self._manage_heartbeat(args)
        else:
            self._emit(self._color(f"Bilinmeyen komut: {command}. /help ile listeyi gorebilirsin.", "yellow"))
        return True

    def _print_help(self) -> None:
        self._emit(
            """
Komutlar
  /status                         Sistem ve kanal durumunu goster
  /agents                         Ajanlari listele
  /agent <ad> on|off|toggle       Ajan durumunu degistir
  /agent show <ad>                Ajan detayini goster
  /agent create <ad> [bayrak]     Yeni ajan olustur
  /agent edit <ad> [bayrak]       Var olan ajani duzenle
  /agent delete <ad> [--yes]      Config ajanini sil
  /agent copy <kaynak> <hedef>    Ajani tool listesiyle birlikte klonla
  /agent test <ad> "gorev"        Tek ajani dogrudan calistir
  /agent pack list                Kurulu agent pack'leri listele
  /agent pack preview <yol>       Pack'i kurmadan incele
  /agent pack install <yol>       Pack kur (--overwrite, --yes)
  /agent pack export <ad>         Kurulumunu paylasilabilir pakete cikar
  /tools [arama]                  Tool'lari listele veya filtrele
  /tools --group <ad>             Bir gruba ait tool'lari listele
  /tools --category <ad>          Bir kategorideki tool'lari listele
  /tools --risk high              Riske gore filtrele (low|medium|high)
  /tools --list-groups            Grup, kategori ve risk dagilimini say
  /tool <ad> on|off|toggle        Tool durumunu degistir
  /tool list                      Custom tool'lari listele
  /tool show <ad> [--code]        Custom tool detayini (ve kodunu) goster
  /tool create <ad> --file <yol>  Yeni custom tool ekle (--code ile satir ici)
  /tool create --file <yol> --names a,b   Tek dosyadan birden fazla tool kaydet
  /tool create --file <yol> --all         Dosyadaki tum fonksiyonlari tool yap
  /tool edit <ad> [bayrak]        Custom tool'u guncelle
  /tool delete <ad> [--yes]       Custom tool'u sil (--keep-file dosyayi birakir)
  /logs [adet]                    Son loglari goster (varsayilan 15)
  /errors [arama]                 Config/runtime hatalarini goster
  /heartbeat                      Zamanlayici ve gorev durumunu goster
  /heartbeat show <id>            Gorev detayini goster
  /heartbeat add --cron X --gorev "..."   Yeni zamanli gorev ekle
  /heartbeat remove <id> [--yes]  Zamanli gorevi sil
  /heartbeat run <id>             Bir heartbeat gorevini simdi calistir
  /heartbeat pause|resume <id>    Gorevi duraklat veya devam ettir
  /heartbeat on|off               Heartbeat config'ini aktif/pasif yap
  /heartbeat reload               Config'i diskten yeniden yukle
  /reload                         Ajan ve custom tool config'ini yenile
  /history                        Terminal sohbet gecmisini goster
  /clear                          Terminal sohbet gecmisini temizle
  /exit                           Uygulamayi guvenli sekilde kapat

Ajan bayraklari
  --model <ad>              Ajanin kullanacagi model (varsayilan: default)
  --tools a,b,c             Tool listesini komple ayarla
  --tool-group g1,g2        Bir grubun tamamini ekle (bkz. /tools --list-groups)
  --tool-category c1,c2     Bir kategorinin tamamini ekle
  --add-tools a,b           Mevcut listeye tool ekle (sadece edit)
  --remove-tools a,b        Mevcut listeden tool cikar (sadece edit)
  --remove-tool-group g1    Bir grubun tamamini cikar (sadece edit)
  --remove-tool-category c1 Bir kategorinin tamamini cikar (sadece edit)
  --tool-mode default|custom
  --prompt "..."            System prompt
  --desc "..."              Aciklama
  --builtin                 SubModels altinda gercek .py dosyasi uret (sadece create)
  --disabled                Pasif olarak olustur (sadece create)
  --enable / --disable      Ajani aktif/pasif yap (sadece edit)
  --dry-run                 Kaydetmeden sonucu goster

Custom tool bayraklari
  --file <yol.py>           Tool kodunu dosyadan al
  --code "..."              Tool kodunu satir ici ver
  --desc "..."              Model bu tool'u ne zaman cagiracagini buradan anlar
  --params "..."            Parametre notu (ornek JSON)
  --env A,B                 Gerekli env degiskenleri (.env.model dosyasina yazilir)
  --names a,b               Tek dosyadan kaydedilecek fonksiyon adlari (toplu kayit)
  --all                     Dosyadaki '_' ile baslamayan tum fonksiyonlari kaydet
  --overwrite               Var olan tool kayitlarinin uzerine yaz (toplu kayit)

NOT: config tipi ajanlar varsayilan tool setini almaz; tool vermezsen ajan
tool'suz calisir. Varsayilan set fallback'i sadece builtin ajanlarda vardir.

Ornekler
  /agent create rapor_ajani --tool-category workspace,memory \\
      --desc "Haftalik rapor derleyici" --prompt "Sen rapor derleyen bir ajansin."
  /agent edit rapor_ajani --tool-group browser_agent --dry-run
  /agent copy sosyal_medya_agent test_sosyal
  /agent test rapor_ajani "Bu haftanin ozetini cikar"
  /tool create fiyat_getir --file ~/fiyat_getir.py --desc "Kripto fiyati doner"
  /tool create --file ~/kripto.py --names fiyat_getir,hacim_getir
  /agent pack export kripto_paketim --agents kripto_ajani --out ~/paketim
  /heartbeat add --cron "*/30" --gorev "Market snapshot al" --name "Market"

Slash ile baslamayan her satir Mimar'a mesaj olarak gonderilir.
""".strip()
        )

    def _print_status(self) -> None:
        uptime = max(0, int(time.time() - getattr(self.base_model, "start_time", time.time())))
        heartbeat = get_heartbeat_status_snapshot()
        automation = get_automation_snapshot()
        self._emit(self._color("Sistem durumu", "bold"))
        self._emit(f"  Model      : {getattr(self.base_model, 'model', '-')}")
        self._emit(f"  Saglayici  : {getattr(self.base_model, 'provider_name', '-')}")
        self._emit(f"  Uptime     : {self._format_duration(uptime)}")
        self._emit(f"  Telegram   : {'aktif' if self.telegram_enabled else 'kapali'}")
        self._emit(f"  Discord    : {'aktif' if self.discord_enabled else 'kapali'}")
        self._emit(
            f"  Heartbeat  : {'calisiyor' if heartbeat.get('running') else 'kapali'} "
            f"({heartbeat.get('job_count', 0)} gorev)"
        )
        if automation.get("busy"):
            self._emit(
                f"  Otomasyon  : mesgul - {automation.get('owner') or '-'} / "
                f"{automation.get('label') or automation.get('job_id') or '-'}"
            )
        else:
            self._emit("  Otomasyon  : hazir")

        errors = self._studio_errors()
        if errors:
            self._emit(
                self._color(
                    f"  Config     : {len(errors)} hata - detay icin /errors",
                    "yellow",
                )
            )
        else:
            self._emit("  Config     : temiz")

    def _studio_errors(self, name: str = "") -> list[dict[str, Any]]:
        """BaseModel'in topladigi agent studio hatalari; istege bagli olarak tek ajana filtreli.

        Bu liste runtime'da doluyor ama hicbir yerde gosterilmiyordu: bilinmeyen tool,
        registry'de bulunamayan submodel, bozuk YAML girdisi hep sessizce yutuluyordu.
        """
        errors = list(getattr(self.base_model, "agent_studio_errors", []) or [])
        if not name:
            return errors
        return [item for item in errors if item.get("name") == name]

    def _print_errors(self, args: list[str]) -> None:
        errors = self._studio_errors()
        needle = " ".join(args).strip().lower()
        if needle:
            errors = [item for item in errors if needle in json.dumps(item, ensure_ascii=False).lower()]

        self._emit(self._color(f"Config hatalari ({len(errors)})", "bold"))
        if not errors:
            self._emit(self._color("  Hata yok.", "green"))
            return
        for item in errors:
            scope = item.get("scope") or "genel"
            target = item.get("name") or ""
            header = f"  [{scope}]" + (f" {target}" if target else "")
            self._emit(self._color(header, "yellow"))
            self._emit(f"      {item.get('message') or '-'}")
            if item.get("entry"):
                self._emit(f"      girdi: {json.dumps(item['entry'], ensure_ascii=False)[:200]}")

    def _print_agents(self) -> None:
        agents = self.base_model.get_hierarchy().get("submodels", [])
        self._emit(self._color(f"Ajanlar ({len(agents)})", "bold"))
        for agent in agents:
            state = "ON " if agent.get("active") else "OFF"
            self._emit(
                f"  [{state}] {agent.get('name')} | {agent.get('model') or '-'} | "
                f"{agent.get('tool_count', len(agent.get('tools') or []))} tool"
            )

    async def _manage_agent(self, args: list[str]) -> None:
        if not args:
            self._emit("Kullanim: /agent <ad> on|off|toggle  ya da  /agent create|edit|delete|show|list|pack ...")
            return

        # Eski kullanim once: /agent <ad> on|off|toggle
        if len(args) == 2 and args[1].lower() in _AGENT_SWITCH_WORDS:
            self._toggle_agent(args[0], args[1].lower())
            return

        studio = _studio()
        action = args[0].lower()
        rest = args[1:]
        try:
            if action == "list":
                self._print_agents()
            elif action == "show":
                self._show_agent(rest)
            elif action == "create":
                self._create_agent(rest)
            elif action == "edit":
                self._edit_agent(rest)
            elif action == "delete":
                await self._delete_agent(rest)
            elif action == "copy":
                self._copy_agent(rest)
            elif action == "test":
                await self._test_agent(rest)
            elif action == "pack":
                await self._manage_agent_pack(rest)
            else:
                self._emit("Kullanim: /agent <ad> on|off|toggle  ya da  /agent create|edit|delete|show|list|pack ...")
        except studio.AgentStudioError as exc:
            self._emit(self._color(f"Agent Studio hatasi: {exc}", "red"))
        except ValueError as exc:
            self._emit(self._color(str(exc), "red"))
        except Exception as exc:
            self._emit(self._color(f"Ajan islemi basarisiz: {exc}", "red"))

    def _toggle_agent(self, name: str, action: str) -> None:
        current = getattr(self.base_model, "active_agents", {}).get(name)
        if current is None:
            self._emit(self._color(f"Ajan bulunamadi: {name}", "red"))
            return
        try:
            target = self._resolve_switch(action, current)
            active = self.base_model.set_agent_active(name, target)
            self._emit(self._color(f"{name}: {'aktif' if active else 'pasif'}", "green"))
        except ValueError as exc:
            self._emit(str(exc))

    def _show_agent(self, args: list[str]) -> None:
        if len(args) != 1:
            self._emit("Kullanim: /agent show <ad>")
            return
        name = _studio().validate_agent_name(args[0])
        entry = self._find_agent_entry(name)
        if entry is None:
            self._emit(self._color(f"Ajan bulunamadi: {name}", "red"))
            return
        self._describe_agent(entry)

    def _create_agent(self, args: list[str]) -> None:
        positional, flags = self._parse_flags(args, bool_flags={"builtin", "disabled", "dry_run"})
        if len(positional) != 1:
            self._emit('Kullanim: /agent create <ad> [--model M] [--tools a,b] [--tool-group g1,g2] [--tool-category c1,c2] [--prompt "..."] [--desc "..."] [--tool-mode default|custom] [--builtin] [--disabled]')
            return

        name = _studio().validate_agent_name(positional[0])
        tools = self._split_name_list(flags.get("tools"))
        expanded = self._expand_tool_selectors(flags, group_key="tool_group", category_key="tool_category")
        if expanded:
            self._emit(f"Grup/kategori secimi {len(expanded)} tool'a genisletildi.")
            tools = list(dict.fromkeys(tools + expanded))
        tool_mode = str(flags.get("tool_mode") or ("custom" if tools else "default")).lower()
        entry = {
            "name": name,
            "type": "builtin" if flags.get("builtin") else "config",
            "enabled": not flags.get("disabled"),
            "description": flags.get("desc") or flags.get("description") or "",
            "model": flags.get("model") or "default",
            "tool_mode": tool_mode,
            "system_prompt": flags.get("prompt") or "",
            "tools": tools,
        }
        self._warn_unknown_tools(tools)
        if not flags.get("builtin") and not tools:
            self._emit(
                self._color(
                    "Uyari: config ajanlari varsayilan tool setini almaz; tool verilmedigi icin bu ajan "
                    "tool'suz calisacak. --tools / --tool-group / --tool-category ile ekleyebilirsin.",
                    "yellow",
                )
            )

        if flags.get("dry_run"):
            self._emit(self._color("[dry-run] Kaydedilmedi. Olusacak ajan:", "yellow"))
            self._describe_agent(entry)
            return

        if flags.get("builtin"):
            result = _studio().create_builtin_agent_scaffold(entry)
            saved = result["agent"]
            self._emit(self._color(f"Builtin ajan olusturuldu: {saved['name']}", "green"))
            self._emit(f"  Submodel dosyasi: {result['path']}")
        else:
            saved = _studio().upsert_agent_config(entry, create=True)
            self._emit(self._color(f"Config ajani olusturuldu: {saved['name']}", "green"))

        self._describe_agent(saved)
        self._reload_agents()

    def _edit_agent(self, args: list[str]) -> None:
        positional, flags = self._parse_flags(args, bool_flags={"enable", "disable", "dry_run"})
        if len(positional) != 1 or not flags:
            self._emit('Kullanim: /agent edit <ad> [--model M] [--tools a,b] [--add-tools a,b] [--remove-tools a,b] [--tool-group g1,g2] [--remove-tool-group g1] [--tool-category c1] [--remove-tool-category c1] [--tool-mode default|custom] [--prompt "..."] [--desc "..."] [--enable|--disable]')
            return

        name = _studio().validate_agent_name(positional[0])
        current = self._find_agent_entry(name)
        if current is None:
            self._emit(self._color(f"Ajan bulunamadi: {name}", "red"))
            return

        merged = dict(current)
        tools_changed = False

        if "model" in flags:
            merged["model"] = flags["model"]
        if "desc" in flags or "description" in flags:
            merged["description"] = flags.get("desc") or flags.get("description") or ""
        if "prompt" in flags:
            merged["system_prompt"] = flags["prompt"]

        # --tools listeyi komple degistirir; digerleri mevcut listeyi baz alir. Varsayilan
        # moddaki builtin ajanin bos listesi "hicbir tool" degil "kendi grubu" demektir,
        # o yuzden ekleme/cikarma oncesi grubu somutlastir.
        if "tools" in flags:
            merged["tools"] = self._split_name_list(flags["tools"])
            tools_changed = True
        elif any(
            key in flags
            for key in ("add_tools", "remove_tools", "tool_group", "tool_category", "remove_tool_group", "remove_tool_category")
        ):
            merged["tools"] = self._materialize_default_tools(merged)

        if "add_tools" in flags:
            additions = self._split_name_list(flags["add_tools"])
            merged["tools"] = list(dict.fromkeys(list(merged.get("tools") or []) + additions))
            tools_changed = True
        group_additions = self._expand_tool_selectors(flags, group_key="tool_group", category_key="tool_category")
        if group_additions:
            self._emit(f"Grup/kategori secimi {len(group_additions)} tool'a genisletildi.")
            merged["tools"] = list(dict.fromkeys(list(merged.get("tools") or []) + group_additions))
            tools_changed = True

        group_removals = self._expand_tool_selectors(
            flags, group_key="remove_tool_group", category_key="remove_tool_category"
        )
        if group_removals:
            self._emit(f"Grup/kategori cikarmasi {len(group_removals)} tool'a genisletildi.")
            dropped = set(group_removals)
            merged["tools"] = [item for item in (merged.get("tools") or []) if item not in dropped]
            tools_changed = True

        if "remove_tools" in flags:
            removals = set(self._split_name_list(flags["remove_tools"]))
            merged["tools"] = [item for item in (merged.get("tools") or []) if item not in removals]
            tools_changed = True

        if tools_changed:
            self._warn_unknown_tools(merged.get("tools") or [])
            merged["tool_mode"] = "custom"
        if "tool_mode" in flags:
            merged["tool_mode"] = str(flags["tool_mode"]).lower()

        if flags.get("enable"):
            merged["enabled"] = True
        if flags.get("disable"):
            merged["enabled"] = False

        if flags.get("dry_run"):
            before = len(current.get("tools") or [])
            after = len(merged.get("tools") or [])
            self._emit(self._color(f"[dry-run] Kaydedilmedi. Tool sayisi {before} -> {after}. Sonuc:", "yellow"))
            self._describe_agent(merged)
            return

        saved = _studio().upsert_agent_config(merged, create=False)
        self._emit(self._color(f"Ajan guncellendi: {saved['name']}", "green"))
        self._describe_agent(saved)
        self._reload_agents()

    def _copy_agent(self, args: list[str]) -> None:
        positional, flags = self._parse_flags(args, bool_flags={"disabled"})
        if len(positional) != 2:
            self._emit('Kullanim: /agent copy <kaynak> <hedef> [--model M] [--desc "..."] [--disabled]')
            return

        source_name = _studio().validate_agent_name(positional[0])
        target_name = _studio().validate_agent_name(positional[1])
        source = self._find_agent_entry(source_name)
        if source is None:
            self._emit(self._color(f"Kaynak ajan bulunamadi: {source_name}", "red"))
            return
        if self._find_agent_entry(target_name) is not None:
            raise ValueError(f"'{target_name}' zaten var.")

        # Builtin kaynagin ortuk grubu klona tasinmaz; kopya her zaman config tipi olur.
        entry = {
            "name": target_name,
            "type": "config",
            "enabled": not flags.get("disabled"),
            "description": flags.get("desc") or flags.get("description") or source.get("description") or "",
            "model": flags.get("model") or source.get("model") or "default",
            "tool_mode": "custom",
            "system_prompt": source.get("system_prompt") or "",
            "tools": self._materialize_default_tools(source),
        }
        saved = _studio().upsert_agent_config(entry, create=True)
        self._emit(self._color(f"'{source_name}' -> '{target_name}' olarak kopyalandi.", "green"))
        self._describe_agent(saved)
        self._reload_agents()

    async def _test_agent(self, args: list[str]) -> None:
        positional, _ = self._parse_flags(args)
        if len(positional) != 2:
            self._emit('Kullanim: /agent test <ad> "gorev metni"')
            return

        name, gorev = positional[0], positional[1]
        runner = getattr(self.base_model, "_submodel_func_map", {}).get(name)
        if runner is None:
            self._emit(self._color(f"Calisan ajan bulunamadi: {name}. /agents ile aktif olanlara bak.", "red"))
            return

        job_id = f"terminal-agent-test-{time.time_ns()}"
        acquired, snapshot = await try_acquire_automation(
            "terminal", job_id=job_id, label=f"Ajan testi: {name}", source="terminal"
        )
        if not acquired:
            owner = snapshot.get("owner") or "otomasyon"
            self._emit(self._color(f"Sistem mesgul: {owner} / {snapshot.get('label') or '-'}", "yellow"))
            return

        self._emit(self._color(f"{name} calistiriliyor...", "yellow"))
        started = time.monotonic()
        try:
            answer = await runner(gorev)
        except Exception as exc:
            self._emit(self._color(f"Ajan hatasi: {exc}", "red"))
            return
        finally:
            await release_automation("terminal", job_id=job_id)

        self._emit(self._color(f"{name}> ({time.monotonic() - started:.1f}sn)", "green"))
        self._emit(str(answer))

    async def _delete_agent(self, args: list[str]) -> None:
        positional, flags = self._parse_flags(args, bool_flags={"yes"})
        if len(positional) != 1:
            self._emit("Kullanim: /agent delete <ad> [--yes]")
            return

        name = _studio().validate_agent_name(positional[0])
        entry = self._find_agent_entry(name)
        if entry is None:
            self._emit(self._color(f"Ajan bulunamadi: {name}", "red"))
            return
        if entry.get("type") == "builtin":
            self._emit(self._color("Builtin ajan silinemez; /agent <ad> off ile pasife alabilirsin.", "yellow"))
            return

        if not flags.get("yes") and not await self._confirm(f"  {name} agents.yaml icinden silinecek. Onayliyor musun? [e/H]: "):
            self._emit("Silme iptal edildi.")
            return

        deleted = _studio().delete_agent_config(name)
        self._emit(self._color(f"Ajan silindi: {deleted['name']}", "green"))
        self._reload_agents()

    async def _manage_agent_pack(self, args: list[str]) -> None:
        if not args:
            self._emit("Kullanim: /agent pack list|preview <yol>|install <yol> [--overwrite] [--yes]")
            return

        action = args[0].lower()
        rest = args[1:]

        if action == "list":
            packs = _studio().load_agent_packs_config()["installed_packs"]
            self._emit(self._color(f"Kurulu pack'ler ({len(packs)})", "bold"))
            if not packs:
                self._emit("  Kurulu pack yok.")
            for pack in packs:
                self._emit(f"  {pack['name']} v{pack['version']} | {pack['type']}")
                self._emit(
                    f"    Ajan: {', '.join(pack['installed_agents']) or '-'} | "
                    f"Tool: {', '.join(pack['installed_tools']) or '-'}"
                )
            return

        if action == "export":
            self._export_agent_pack(rest)
            return

        if action not in {"preview", "install"}:
            self._emit(
                "Kullanim: /agent pack list|preview <yol>|install <yol> [--overwrite] [--yes]|"
                "export <ad> [--agents a,b] [--tools c,d] [--all] [--out <klasor>]"
            )
            return

        positional, flags = self._parse_flags(rest, bool_flags={"overwrite", "yes"})
        if len(positional) != 1:
            self._emit(f"Kullanim: /agent pack {action} <yol>" + (" [--overwrite] [--yes]" if action == "install" else ""))
            return

        path_value = positional[0]
        preview = _studio().preview_agent_pack(path_value)
        self._print_pack_preview(preview)

        if action == "preview":
            return
        if not preview["installable"]:
            self._emit(self._color("Pack kurulabilir durumda degil; kurulum yapilmadi.", "red"))
            return
        if not flags.get("yes") and not await self._confirm(f"  {preview['name']} kurulacak. Onayliyor musun? [e/H]: "):
            self._emit("Kurulum iptal edildi.")
            return

        result = _studio().install_agent_pack(path_value, overwrite=bool(flags.get("overwrite")))
        pack = result["pack"]
        self._emit(self._color(f"Pack kuruldu: {pack['name']} v{pack['version']}", "green"))
        self._emit(f"  Konum: {pack['installed_path']}")
        self._emit(f"  Ajanlar: {', '.join(pack['installed_agents']) or '-'}")
        self._emit(f"  Tool'lar: {', '.join(pack['installed_tools']) or '-'}")
        self._reload_agents()

    def _export_agent_pack(self, args: list[str]) -> None:
        positional, flags = self._parse_flags(args, bool_flags={"all", "overwrite"})
        if len(positional) != 1:
            self._emit(
                'Kullanim: /agent pack export <pack_adi> [--agents a,b] [--tools c,d] [--all] '
                '[--out <klasor>] [--version 0.1.0] [--desc "..."] [--overwrite]'
            )
            self._emit("   --agents verilmezse ajanlarin kullandigi custom tool'lar otomatik toplanir.")
            return

        result = _studio().export_agent_pack(
            positional[0],
            out_dir=str(flags.get("out") or ""),
            agents=self._split_name_list(flags.get("agents")),
            tools=self._split_name_list(flags.get("tools")),
            include_all=bool(flags.get("all")),
            version=str(flags.get("version") or "0.1.0"),
            description=str(flags.get("desc") or flags.get("description") or ""),
            overwrite=bool(flags.get("overwrite")),
        )

        self._emit(self._color(f"Pack olusturuldu: {result['name']} v{result['version']} ({result['type']})", "green"))
        self._emit(f"  Konum   : {result['path']}")
        self._emit(f"  Ajanlar : {', '.join(result['agents']) or '-'}")
        self._emit(f"  Tool'lar: {', '.join(result['tools']) or '-'}")
        if result["env_vars"]:
            self._emit(f"  Env     : {', '.join(result['env_vars'])} (env.example'a sadece adlar yazildi)")
        self._emit("  Dosyalar:")
        for item in result["files"]:
            self._emit(f"    {item}")
        for warning in result["warnings"]:
            self._emit(self._color(f"  Uyari: {warning}", "yellow"))
        self._emit(f"  Kurmak icin: /agent pack install {result['path']}")

    def _print_pack_preview(self, preview: dict[str, Any]) -> None:
        self._emit(self._color(f"Pack: {preview['name']} v{preview['version']} ({preview['type']})", "bold"))
        if preview.get("description"):
            self._emit(f"  Aciklama: {preview['description']}")
        self._emit(f"  Konum: {preview['path']}")
        self._emit(f"  Ajanlar ({len(preview['agents'])}):")
        for agent in preview["agents"]:
            self._emit(f"    {agent['name']} | {agent['type']} | {len(agent.get('tools') or [])} tool")
        self._emit(f"  Tool'lar ({len(preview['tools'])}):")
        for tool in preview["tools"]:
            state = "OK " if tool.get("export_ok") else "HATA"
            self._emit(f"    [{state}] {tool['name']}")
        for warning in preview["warnings"]:
            self._emit(self._color(f"  Uyari: {warning}", "yellow"))
        for error in preview["errors"]:
            self._emit(self._color(f"  Hata: {error}", "red"))
        self._emit(
            self._color(
                f"  Kurulabilir: {'evet' if preview['installable'] else 'hayir'}",
                "green" if preview["installable"] else "red",
            )
        )

    def _describe_agent(self, entry: dict[str, Any]) -> None:
        self._emit(self._color(f"Ajan: {entry['name']}", "bold"))
        self._emit(f"  Tip       : {entry.get('type') or 'config'}")
        self._emit(f"  Durum     : {'aktif' if entry.get('enabled') else 'pasif'}")
        self._emit(f"  Model     : {entry.get('model') or 'default'}")
        self._emit(f"  Tool modu : {entry.get('tool_mode') or 'default'}")
        if entry.get("description"):
            self._emit(f"  Aciklama  : {entry['description']}")
        tools = entry.get("tools") or []
        if tools:
            self._emit(f"  Tool'lar  : {', '.join(tools)} ({len(tools)} adet)")
        elif entry.get("type") == "builtin" and entry.get("tool_mode") != "custom":
            self._emit(f"  Tool'lar  : (varsayilan set: '{entry['name']}' grubu)")
        else:
            # Config ajanlari icin tool_mode yok sayilir; bos liste = gercekten tool'suz.
            self._emit(self._color("  Tool'lar  : (bos - bu ajan hicbir tool kullanamaz)", "yellow"))
        prompt = str(entry.get("system_prompt") or "").strip()
        if prompt:
            first_line = prompt.splitlines()[0]
            suffix = "..." if len(prompt) > len(first_line) else ""
            self._emit(f"  Prompt    : {first_line[:90]}{suffix} ({len(prompt)} karakter)")
        for error in self._studio_errors(entry["name"]):
            self._emit(self._color(f"  Hata      : {error.get('message')}", "yellow"))

    @staticmethod
    def _find_agent_entry(name: str) -> dict[str, Any] | None:
        agents = _studio().load_agents_config()["agents"]
        return next((item for item in agents if item["name"] == name), None)

    @staticmethod
    def _tool_taxonomy() -> list[dict[str, Any]]:
        """Tool kayit defteri: her tool icin ad, kategori ve ait oldugu gruplar."""
        return _studio().build_tool_registry()["tools"]

    def _materialize_default_tools(self, entry: dict[str, Any]) -> list[str]:
        """Varsayilan moddaki builtin ajanin ortuk tool setini acik listeye cevirir.

        BaseModel builtin ajanlar icin bos listeyi 'ajan adiyla ayni gruba ait tum
        tool'lar' diye yorumluyor. Ekleme/cikarma yapmadan once bunu somutlastirmazsak
        tek tool eklemek ajanin butun varsayilan setini silmis olur.
        """
        tools = list(entry.get("tools") or [])
        if tools or entry.get("type") != "builtin" or entry.get("tool_mode") == "custom":
            return tools
        try:
            registry = self._tool_taxonomy()
        except Exception:
            return tools
        defaults = sorted(
            tool["name"] for tool in registry if entry["name"] in (tool.get("groups") or [])
        )
        if defaults:
            self._emit(
                f"'{entry['name']}' varsayilan setinden {len(defaults)} tool acik listeye alindi."
            )
        return defaults

    @staticmethod
    def _assert_known_taxonomy(registry: list[dict[str, Any]], groups, categories) -> None:
        """Bilinmeyen grup/kategori adlarini sessizce bos sonuca dusurmek yerine hata verir."""
        known_groups = sorted({group for tool in registry for group in tool.get("groups") or []})
        known_categories = sorted({tool["category"] for tool in registry})

        unknown_groups = [item for item in groups if item not in known_groups]
        if unknown_groups:
            raise ValueError(
                f"Bilinmeyen tool grubu: {', '.join(unknown_groups)}. Gecerli gruplar: {', '.join(known_groups)}"
            )
        unknown_categories = [item for item in categories if item not in known_categories]
        if unknown_categories:
            raise ValueError(
                f"Bilinmeyen tool kategorisi: {', '.join(unknown_categories)}. "
                f"Gecerli kategoriler: {', '.join(known_categories)}"
            )

    def _expand_tool_selectors(self, flags: dict[str, Any], *, group_key: str, category_key: str) -> list[str]:
        """--tool-group / --tool-category degerlerini tool adlarina cevirir."""
        wanted_groups = self._split_name_list(flags.get(group_key))
        wanted_categories = self._split_name_list(flags.get(category_key))
        if not wanted_groups and not wanted_categories:
            return []

        registry = self._tool_taxonomy()
        self._assert_known_taxonomy(registry, wanted_groups, wanted_categories)

        selected = [
            tool["name"]
            for tool in registry
            if any(group in wanted_groups for group in tool.get("groups") or [])
            or tool["category"] in wanted_categories
        ]
        return sorted(dict.fromkeys(selected))

    def _warn_unknown_tools(self, tools: list[str]) -> None:
        if not tools:
            return
        try:
            known = set(_studio().load_available_tools(include_custom=True)["tools"].keys())
        except Exception:
            return
        unknown = [tool for tool in tools if tool not in known]
        if unknown:
            self._emit(
                self._color(
                    f"Uyari: kayitli olmayan tool'lar yok sayilacak: {', '.join(unknown)}",
                    "yellow",
                )
            )

    async def _confirm(self, prompt: str) -> bool:
        try:
            answer = await self._read_line(prompt)
        except (EOFError, KeyboardInterrupt):
            return False
        return (answer or "").strip().lower() in _AFFIRMATIVE_ANSWERS

    @staticmethod
    def _split_name_list(value: Any) -> list[str]:
        if not value:
            return []
        raw = str(value).replace(",", " ").split()
        return list(dict.fromkeys(item.strip() for item in raw if item.strip()))

    @staticmethod
    def _parse_flags(args: list[str], *, bool_flags: set[str] | frozenset[str] = frozenset()) -> tuple[list[str], dict[str, Any]]:
        positional: list[str] = []
        flags: dict[str, Any] = {}
        index = 0
        while index < len(args):
            token = args[index]
            if token.startswith("--"):
                key = token[2:].strip().lower().replace("-", "_")
                if not key:
                    raise ValueError(f"Gecersiz bayrak: {token}")
                if key in bool_flags:
                    flags[key] = True
                    index += 1
                    continue
                if index + 1 >= len(args):
                    raise ValueError(f"--{key} icin deger verilmedi.")
                flags[key] = args[index + 1]
                index += 2
                continue
            positional.append(token)
            index += 1
        return positional, flags

    def _all_tools(self) -> list[dict]:
        hierarchy = self.base_model.get_hierarchy()
        tools = list(hierarchy.get("tools", []))
        for agent in hierarchy.get("submodels", []):
            tools.extend(agent.get("tools", []))
        unique = {}
        for tool in tools:
            unique.setdefault(tool.get("name"), tool)
        return [tool for name, tool in sorted(unique.items()) if name]

    def _print_tools(self, args: list[str]) -> None:
        try:
            positional, flags = self._parse_flags(args, bool_flags={"list_groups"})
        except ValueError as exc:
            self._emit(self._color(str(exc), "red"))
            return

        if flags.get("list_groups"):
            self._print_tool_taxonomy()
            return

        needle = " ".join(positional).strip().lower()
        wanted_groups = set(self._split_name_list(flags.get("group")))
        wanted_categories = set(self._split_name_list(flags.get("category")))
        wanted_risks = set(self._split_name_list(flags.get("risk")))
        if wanted_risks - {"low", "medium", "high"}:
            self._emit(self._color("--risk sadece low, medium veya high olabilir.", "red"))
            return

        taxonomy: dict[str, dict[str, Any]] = {}
        if wanted_groups or wanted_categories or wanted_risks:
            try:
                registry = self._tool_taxonomy()
                self._assert_known_taxonomy(registry, wanted_groups, wanted_categories)
                taxonomy = {tool["name"]: tool for tool in registry}
            except ValueError as exc:
                self._emit(self._color(str(exc), "red"))
                return
            except Exception as exc:
                self._emit(self._color(f"Tool taksonomisi okunamadi: {exc}", "red"))
                return

        tools = []
        for tool in self._all_tools():
            name = tool.get("name", "")
            if needle and needle not in name.lower() and needle not in tool.get("desc", "").lower():
                continue
            if taxonomy:
                meta = taxonomy.get(name)
                if not meta:
                    continue
                if wanted_groups and not (wanted_groups & set(meta.get("groups") or [])):
                    continue
                if wanted_categories and meta.get("category") not in wanted_categories:
                    continue
                if wanted_risks and meta.get("risk") not in wanted_risks:
                    continue
            tools.append(tool)

        self._emit(self._color(f"Tool'lar ({len(tools)})", "bold"))
        if not tools:
            self._emit("  Eslesen tool yok.")
            return
        for tool in tools:
            state = "ON " if tool.get("active", True) else "OFF"
            meta = taxonomy.get(tool.get("name", ""))
            suffix = f" | {meta['category']} | risk={meta['risk']}" if meta else ""
            self._emit(f"  [{state}] {tool.get('name')}{suffix}")

    def _print_tool_taxonomy(self) -> None:
        try:
            registry = self._tool_taxonomy()
        except Exception as exc:
            self._emit(self._color(f"Tool taksonomisi okunamadi: {exc}", "red"))
            return

        group_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        for tool in registry:
            for group in tool.get("groups") or []:
                group_counts[group] = group_counts.get(group, 0) + 1
            category_counts[tool["category"]] = category_counts.get(tool["category"], 0) + 1

        self._emit(self._color(f"Tool gruplari ({len(group_counts)})", "bold"))
        for name, count in sorted(group_counts.items(), key=lambda item: (-item[1], item[0])):
            self._emit(f"  {name:24} {count} tool")
        self._emit(self._color(f"Tool kategorileri ({len(category_counts)})", "bold"))
        for name, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0])):
            self._emit(f"  {name:24} {count} tool")
        risk_counts: dict[str, int] = {}
        for tool in registry:
            risk_counts[tool["risk"]] = risk_counts.get(tool["risk"], 0) + 1
        self._emit(self._color("Risk dagilimi", "bold"))
        for level in ("high", "medium", "low"):
            if level in risk_counts:
                self._emit(f"  {level:24} {risk_counts[level]} tool")
        self._emit(f"Toplam {len(registry)} tool.")
        self._emit("Kullanim: /tools --group <ad> | --category <ad> | --risk high")

    async def _manage_tool(self, args: list[str]) -> None:
        if not args:
            self._emit("Kullanim: /tool <ad> on|off|toggle  ya da  /tool create|edit|show|delete ...")
            return

        # Eski kullanim once: /tool <ad> on|off|toggle
        if len(args) == 2 and args[1].lower() in _AGENT_SWITCH_WORDS:
            self._toggle_tool(args[0], args[1].lower())
            return

        action = args[0].lower()
        rest = args[1:]
        studio = _studio()
        try:
            if action == "create":
                self._upsert_custom_tool(rest, create=True)
            elif action == "edit":
                self._upsert_custom_tool(rest, create=False)
            elif action == "show":
                self._show_custom_tool(rest)
            elif action == "list":
                self._print_custom_tools()
            elif action == "delete":
                await self._delete_custom_tool(rest)
            else:
                self._emit("Kullanim: /tool <ad> on|off|toggle  ya da  /tool create|edit|show|list|delete ...")
        except studio.AgentStudioError as exc:
            self._emit(self._color(f"Agent Studio hatasi: {exc}", "red"))
        except ValueError as exc:
            self._emit(self._color(str(exc), "red"))
        except Exception as exc:
            self._emit(self._color(f"Tool islemi basarisiz: {exc}", "red"))

    def _toggle_tool(self, name: str, action: str) -> None:
        current = getattr(self.base_model, "active_tools", {}).get(name)
        if current is None:
            self._emit(self._color(f"Tool bulunamadi: {name}", "red"))
            return
        try:
            target = self._resolve_switch(action, current)
            active = self.base_model.set_tool_active(name, target)
            self._emit(self._color(f"{name}: {'aktif' if active else 'pasif'}", "green"))
        except ValueError as exc:
            self._emit(str(exc))

    @staticmethod
    def _find_custom_tool(name: str) -> dict[str, Any] | None:
        entries = _studio().load_custom_tools_config()["custom_tools"]
        return next((item for item in entries if item["name"] == name), None)

    def _print_custom_tools(self) -> None:
        entries = _studio().load_custom_tools_config()["custom_tools"]
        self._emit(self._color(f"Custom tool'lar ({len(entries)})", "bold"))
        if not entries:
            self._emit("  Kayitli custom tool yok.")
            return
        for entry in entries:
            state = "ON " if entry.get("enabled") else "OFF"
            self._emit(f"  [{state}] {entry['name']} | {entry.get('file') or '-'}")
            if entry.get("description"):
                self._emit(f"        {entry['description']}")

    def _parse_env_flag(self, value: Any) -> dict[str, str]:
        """--env AD,BASKA_AD=deger -> {AD: '', BASKA_AD: 'deger'}.

        Degeri verilen degiskenler .env.model dosyasina yazilir; degersiz olanlar
        sadece tool'un gereksinim listesine kaydedilir.
        """
        result: dict[str, str] = {}
        for item in self._split_name_list(value):
            key, _, raw_value = item.partition("=")
            key = key.strip().upper()
            if not key:
                continue
            result[key] = raw_value.strip()
        return result

    def _read_tool_code(self, flags: dict[str, Any]) -> str | None:
        """--file veya --code bayragindan tool kaynak kodunu okur."""
        if "code" in flags:
            return str(flags["code"])
        if "file" in flags:
            path = Path(str(flags["file"])).expanduser()
            if not path.is_file():
                raise ValueError(f"Dosya bulunamadi: {path}")
            if path.suffix != ".py":
                raise ValueError("Tool dosyasi .py uzantili olmali.")
            return path.read_text(encoding="utf-8")
        return None

    def _upsert_custom_tool(self, args: list[str], *, create: bool) -> None:
        positional, flags = self._parse_flags(
            args, bool_flags={"disabled", "enable", "disable", "all", "overwrite"}
        )
        label = "create" if create else "edit"

        # Toplu kayit: tek dosyadaki birden fazla fonksiyonu ayri tool olarak ekle.
        if create and ("names" in flags or flags.get("all")):
            if positional:
                raise ValueError("Toplu kayitta tool adi verilmez; adlar --names ile ya da --all ile belirlenir.")
            self._create_tools_from_file(flags)
            return

        if len(positional) != 1:
            self._emit(
                f'Kullanim: /tool {label} <ad> [--file <yol.py>] [--code "..."] [--desc "..."] '
                '[--params "..."] [--env A,B]' + (" [--disabled]" if create else " [--enable|--disable]")
            )
            if create:
                self._emit('   Toplu: /tool create --file <yol.py> --names a,b   ya da   --all')
            return

        name = _studio().validate_tool_name(positional[0])
        existing = self._find_custom_tool(name)
        if create and existing:
            raise ValueError(f"'{name}' zaten kayitli. Guncellemek icin /tool edit kullan.")
        if not create and not existing:
            raise ValueError(f"'{name}' bulunamadi. Olusturmak icin /tool create kullan.")

        code = self._read_tool_code(flags)
        if create and code is None:
            raise ValueError("Yeni tool icin --file <yol.py> ya da --code \"...\" vermelisin.")
        if code is None:
            code = _studio().read_custom_tool_code(existing)

        # Kaydetmeden once derle: bozuk kod runtime'a girmesin.
        try:
            compile(code, f"<custom_tool:{name}>", "exec")
        except SyntaxError as exc:
            raise ValueError(f"Kod derlenemedi (satir {exc.lineno}): {exc.msg}") from exc
        if not re.search(rf"(?m)^\s*(?:async\s+)?def\s+{re.escape(name)}\s*\(", code):
            raise ValueError(f"Kod icinde '{name}' adinda bir fonksiyon tanimi bulunamadi.")

        base = existing or {}
        description = flags.get("desc") or flags.get("description") or base.get("description") or ""
        params_note = flags.get("params") or flags.get("params_note") or base.get("params_note") or ""
        env_vars = self._parse_env_flag(flags.get("env")) or {
            name: "" for name in base.get("env_vars") or []
        }
        enabled = bool(base.get("enabled", True))
        if flags.get("disabled") or flags.get("disable"):
            enabled = False
        if flags.get("enable"):
            enabled = True

        saved = _studio().upsert_custom_tool(
            name,
            description,
            code,
            enabled=enabled,
            params_note=params_note,
            env_vars=env_vars,
        )
        self._emit(self._color(f"Custom tool {'olusturuldu' if create else 'guncellendi'}: {name}", "green"))
        self._emit(f"  Dosya: {saved['path']}")

        # Import edilebiliyor mu? Kayit sonrasi gercek yukleme denemesi.
        func, error = _studio().load_custom_tool_callable(saved, include_disabled=True)
        if error or func is None:
            self._emit(self._color(f"  Uyari: tool yuklenemedi -> {error or 'bilinmeyen hata'}", "yellow"))
        else:
            self._emit(self._color("  Yukleme testi: basarili", "green"))
        if saved.get("env_vars"):
            self._emit(f"  Env: {', '.join(saved['env_vars'])} (.env.model dosyasina eklendi)")
        if not description:
            self._emit(self._color("  Uyari: aciklama bos; model bu tool'u ne zaman cagiracagini bilemez.", "yellow"))

        self._reload_agents()

    @staticmethod
    def _module_functions(code: str) -> list[tuple[str, str]]:
        """Modulun ust seviye fonksiyonlarini (ad, docstring ilk satiri) olarak dondurur."""
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise ValueError(f"Kod derlenemedi (satir {exc.lineno}): {exc.msg}") from exc
        functions = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = (ast.get_docstring(node) or "").strip()
                functions.append((node.name, doc.splitlines()[0] if doc else ""))
        return functions

    def _create_tools_from_file(self, flags: dict[str, Any]) -> None:
        """Tek dosyadan birden fazla tool kaydeder.

        Dosya kaynak adiyla bir kez kopyalanir ve her tool kaydi ayni dosyayi
        gosterir; runtime tool'u modulden adiyla cekiyor (getattr), bu yuzden bir
        modul birden fazla tool tasiyabilir. Agent pack kurulumu da ayni sekilde
        calisir.
        """
        studio = _studio()
        if "file" not in flags:
            raise ValueError("Toplu kayit icin --file <yol.py> gerekli.")

        source = Path(str(flags["file"])).expanduser()
        if not source.is_file():
            raise ValueError(f"Dosya bulunamadi: {source}")
        if source.suffix != ".py":
            raise ValueError("Tool dosyasi .py uzantili olmali.")

        code = source.read_text(encoding="utf-8")
        functions = self._module_functions(code)
        available = {name for name, _ in functions}
        docs = dict(functions)

        if flags.get("all"):
            names = [name for name, _ in functions if not name.startswith("_")]
            if not names:
                raise ValueError("Dosyada '_' ile baslamayan ust seviye fonksiyon yok.")
        else:
            names = [studio.validate_tool_name(item) for item in self._split_name_list(flags["names"])]
            if not names:
                raise ValueError("--names bos.")
            missing = [name for name in names if name not in available]
            if missing:
                raise ValueError(
                    f"Dosyada bulunmayan fonksiyon: {', '.join(missing)}. "
                    f"Mevcut: {', '.join(sorted(available)) or '(yok)'}"
                )

        config = studio.load_custom_tools_config()
        entries = list(config["custom_tools"])
        by_name = {entry["name"]: entry for entry in entries}
        builtin_names = {
            item["name"] for item in studio.build_tool_registry()["tools"] if item.get("source") != "custom"
        }

        clashes = [name for name in names if name in by_name or name in builtin_names]
        if clashes and not flags.get("overwrite"):
            raise ValueError(f"Zaten kayitli tool: {', '.join(clashes)}. Uzerine yazmak icin --overwrite kullan.")

        target = Path(studio.CUSTOM_TOOLS_DIR) / source.name
        if target.exists() and target.resolve() != source.resolve() and not flags.get("overwrite"):
            existing_users = [entry["name"] for entry in entries if entry.get("file") == source.name]
            if existing_users:
                raise ValueError(
                    f"{source.name} zaten kullanimda ({', '.join(existing_users)}). --overwrite ile guncelle."
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

        env_vars = self._parse_env_flag(flags.get("env"))
        env_names = studio.update_model_env_vars(env_vars) or list(env_vars)
        shared_desc = flags.get("desc") or flags.get("description") or ""
        enabled = not flags.get("disabled")

        for name in names:
            entry = {
                "name": name,
                "enabled": enabled,
                "description": docs.get(name) or shared_desc,
                "file": target.name,
                "params_note": flags.get("params") or flags.get("params_note") or "",
                "env_vars": [item.upper() for item in env_names],
            }
            entries = [item for item in entries if item["name"] != name]
            entries.append(entry)

        studio.save_custom_tools_config(entries)
        self._emit(self._color(f"{len(names)} tool kaydedildi: {', '.join(names)}", "green"))
        self._emit(f"  Dosya: {target} (tek kopya, {len(names)} kayit paylasiyor)")

        by_name = {entry["name"]: entry for entry in studio.load_custom_tools_config()["custom_tools"]}
        for name in names:
            func, error = studio.load_custom_tool_callable(by_name[name], include_disabled=True)
            if error or func is None:
                self._emit(self._color(f"  [HATA] {name}: {error or 'yuklenemedi'}", "red"))
            else:
                self._emit(self._color(f"  [OK  ] {name}: {by_name[name]['description'] or '(aciklama yok)'}", "green"))

        skipped = sorted(available - set(names))
        if skipped:
            self._emit(f"  Kaydedilmeyen fonksiyonlar: {', '.join(skipped)}")
        self._reload_agents()

    def _show_custom_tool(self, args: list[str]) -> None:
        positional, flags = self._parse_flags(args, bool_flags={"code"})
        if len(positional) != 1:
            self._emit("Kullanim: /tool show <ad> [--code]")
            return
        name = _studio().validate_tool_name(positional[0])
        entry = self._find_custom_tool(name)
        if entry is None:
            self._emit(self._color(f"Custom tool bulunamadi: {name}", "red"))
            return

        self._emit(self._color(f"Custom tool: {entry['name']}", "bold"))
        self._emit(f"  Durum     : {'aktif' if entry.get('enabled') else 'pasif'}")
        self._emit(f"  Dosya     : {entry.get('file') or '-'}")
        self._emit(f"  Aciklama  : {entry.get('description') or '-'}")
        if entry.get("params_note"):
            self._emit(f"  Parametre : {entry['params_note']}")
        if entry.get("env_vars"):
            self._emit(f"  Env       : {', '.join(entry['env_vars'])}")

        func, error = _studio().load_custom_tool_callable(entry, include_disabled=True)
        if error or func is None:
            self._emit(self._color(f"  Yukleme   : HATA -> {error or 'bilinmeyen'}", "red"))
        else:
            self._emit(self._color("  Yukleme   : basarili", "green"))

        if flags.get("code"):
            code = _studio().read_custom_tool_code(entry)
            self._emit(self._color("--- kod ---", "bold"))
            for line_no, line in enumerate(code.splitlines(), start=1):
                self._emit(f"  {line_no:3} | {line}")

    async def _delete_custom_tool(self, args: list[str]) -> None:
        positional, flags = self._parse_flags(args, bool_flags={"yes", "keep_file"})
        if len(positional) != 1:
            self._emit("Kullanim: /tool delete <ad> [--yes] [--keep-file]")
            return
        name = _studio().validate_tool_name(positional[0])
        entry = self._find_custom_tool(name)
        if entry is None:
            self._emit(self._color(f"Custom tool bulunamadi: {name}", "red"))
            return

        users = [
            agent["name"]
            for agent in _studio().load_agents_config()["agents"]
            if name in (agent.get("tools") or [])
        ]
        if users:
            self._emit(self._color(f"Uyari: bu tool su ajanlarda kayitli: {', '.join(users)}", "yellow"))

        if not flags.get("yes") and not await self._confirm(f"  {name} silinecek. Onayliyor musun? [e/H]: "):
            self._emit("Silme iptal edildi.")
            return

        studio = _studio()
        entries = [item for item in studio.load_custom_tools_config()["custom_tools"] if item["name"] != name]
        studio.save_custom_tools_config(entries)

        if not flags.get("keep_file"):
            path = Path(studio.CUSTOM_TOOLS_DIR) / (entry.get("file") or f"{name}.py")
            try:
                path.unlink()
                self._emit(f"  Dosya silindi: {path}")
            except FileNotFoundError:
                pass
            except Exception as exc:
                self._emit(self._color(f"  Dosya silinemedi: {exc}", "yellow"))

        self._emit(self._color(f"Custom tool silindi: {name}", "green"))
        self._reload_agents()

    def _print_logs(self, args: list[str]) -> None:
        try:
            count = min(100, max(1, int(args[0]))) if args else 15
        except ValueError:
            self._emit("Kullanim: /logs [adet]")
            return
        logs = list(getattr(self.base_model, "logs", []))[-count:]
        self._emit(self._color(f"Son loglar ({len(logs)})", "bold"))
        for item in logs:
            self._emit(f"  {item.get('time', '--:--:--')} [{item.get('type', 'log')}] {item.get('message', '')}")

    def _print_history(self) -> None:
        if not self.history:
            self._emit("Sohbet gecmisi bos.")
            return
        self._emit(self._color(f"Sohbet gecmisi ({len(self.history)})", "bold"))
        for item in self.history:
            label = "Sen" if item.get("role") == "user" else "Mimar"
            self._emit(f"  {item.get('time', '--:--')} {label}: {item.get('content', '')}")

    def _clear_history(self) -> None:
        self.history = []
        self._save_history()
        self._emit(self._color("Terminal sohbet gecmisi temizlendi.", "green"))

    def _reload_agents(self) -> None:
        hierarchy = self.base_model.reload_agent_studio()
        self._emit(
            self._color(
                f"Runtime yenilendi: {len(hierarchy.get('submodels', []))} ajan, "
                f"{len(hierarchy.get('tools', []))} base tool.",
                "green",
            )
        )

    async def _manage_heartbeat(self, args: list[str]) -> None:
        if not args:
            status = get_heartbeat_status_snapshot()
            jobs = get_heartbeat_jobs_snapshot()
            self._emit(self._color("Heartbeat", "bold"))
            self._emit(
                f"  Servis: {'calisiyor' if status.get('running') else 'kapali'} | "
                f"Config: {'aktif' if status.get('enabled') else 'pasif'} | {len(jobs)} gorev"
            )
            for job in jobs:
                self._emit(
                    f"  [{'RUN' if job.get('running') else 'ON ' if not job.get('paused') else 'OFF'}] "
                    f"{job.get('job_id')} | {job.get('name') or '-'} | sonraki: {job.get('next_run_at') or '-'}"
                )
            return

        action = args[0].lower()
        rest = args[1:]
        try:
            if action == "reload" and len(args) == 1:
                result = await reload_heartbeat_service(reason="terminal_reload")
            elif action in {"run", "pause", "resume"} and len(args) == 2:
                job_id = args[1]
                operations = {
                    "run": run_heartbeat_job,
                    "pause": pause_heartbeat_job,
                    "resume": resume_heartbeat_job,
                }
                result = await operations[action](job_id)
            elif action == "show" and len(rest) == 1:
                self._show_heartbeat_task(rest[0])
                return
            elif action == "add":
                await self._add_heartbeat_task(rest)
                return
            elif action == "remove":
                await self._remove_heartbeat_task(rest)
                return
            elif action in {"on", "off"} and not rest:
                await self._set_heartbeat_enabled(action == "on")
                return
            else:
                self._emit(
                    "Kullanim: /heartbeat [reload|run <id>|pause <id>|resume <id>|show <id>|"
                    'add --cron X --gorev "..."|remove <id>|on|off]'
                )
                return
            self._emit(self._color(f"Heartbeat islemi tamamlandi: {result}", "green"))
        except HeartbeatConfigError as exc:
            self._emit(self._color(f"Heartbeat config hatasi: {exc}", "red"))
        except ValueError as exc:
            self._emit(self._color(str(exc), "red"))
        except Exception as exc:
            self._emit(self._color(f"Heartbeat hatasi: {exc}", "red"))

    def _show_heartbeat_task(self, task_id: str) -> None:
        tasks = parse_config_content(read_config_content())["tasks"]
        task = next((item for item in tasks if item.task_id == task_id), None)
        if task is None:
            self._emit(self._color(f"Heartbeat gorevi bulunamadi: {task_id}", "red"))
            return
        self._emit(self._color(f"Heartbeat gorevi: {task.task_id}", "bold"))
        self._emit(f"  Ad     : {task.name}")
        self._emit(f"  Cron   : {task.cron}")
        self._emit(f"  Durum  : {'aktif' if task.enabled else 'pasif'}")
        self._emit("  Gorev  :")
        for line in task.gorev.splitlines():
            self._emit(f"    {line}")

    async def _add_heartbeat_task(self, args: list[str]) -> None:
        positional, flags = self._parse_flags(args, bool_flags={"disabled", "dry_run"})
        if positional or "cron" not in flags or "gorev" not in flags:
            self._emit(
                'Kullanim: /heartbeat add --cron <startup|*/N|HH:MM> --gorev "..." '
                '[--id <id>] [--name "..."] [--disabled] [--dry-run]'
            )
            return

        content = read_config_content()
        updated, task_id = add_task_to_content(
            content,
            gorev=str(flags["gorev"]),
            cron=str(flags["cron"]),
            task_id=str(flags.get("id") or ""),
            name=str(flags.get("name") or ""),
            enabled=not flags.get("disabled"),
        )

        if flags.get("dry_run"):
            self._emit(self._color(f"[dry-run] Eklenecek gorev: {task_id}", "yellow"))
            self._emit("\n".join(f"  {line}" for line in updated.splitlines()[-8:]))
            return

        write_config_content(updated)
        self._emit(self._color(f"Heartbeat gorevi eklendi: {task_id}", "green"))
        await self._refresh_heartbeat("terminal_task_add")

    async def _remove_heartbeat_task(self, args: list[str]) -> None:
        positional, flags = self._parse_flags(args, bool_flags={"yes"})
        if len(positional) != 1:
            self._emit("Kullanim: /heartbeat remove <id> [--yes]")
            return

        task_id = positional[0]
        content = read_config_content()
        updated = remove_task_from_content(content, task_id)

        if not flags.get("yes") and not await self._confirm(f"  {task_id} gorevi silinecek. Onayliyor musun? [e/H]: "):
            self._emit("Silme iptal edildi.")
            return

        write_config_content(updated)
        self._emit(self._color(f"Heartbeat gorevi silindi: {task_id}", "green"))
        await self._refresh_heartbeat("terminal_task_remove")

    async def _refresh_heartbeat(self, reason: str) -> None:
        """Config yazildiktan sonra zamanlayiciyi tazeler.

        Servis henuz ayakta degilse bu bir hata degil: config diske yazildi ve
        heartbeat baslarken okunacak.
        """
        try:
            result = await reload_heartbeat_service(reason=reason)
        except Exception as exc:
            self._emit(self._color(f"  Config kaydedildi; zamanlayici tazelenemedi ({exc}).", "yellow"))
            return
        self._emit(f"  Zamanlayici yenilendi: {result}")

    async def _set_heartbeat_enabled(self, enabled: bool) -> None:
        updated = set_enabled_in_content(read_config_content(), enabled)
        write_config_content(updated)
        self._emit(self._color(f"Heartbeat config: {'aktif' if enabled else 'pasif'}", "green"))
        await self._refresh_heartbeat("terminal_toggle")

    async def _chat(self, user_text: str) -> None:
        job_id = f"terminal-chat-{time.time_ns()}"
        acquired, snapshot = await try_acquire_automation(
            "terminal",
            job_id=job_id,
            label="Terminal sohbet istegi",
            source="terminal",
        )
        if not acquired:
            owner = snapshot.get("owner") or "otomasyon"
            label = snapshot.get("label") or snapshot.get("job_id") or "aktif gorev"
            self._emit(self._color(f"Sistem mesgul: {owner} / {label}", "yellow"))
            return

        context = self._build_context()
        self._add_history("user", user_text)
        self._emit(self._color("Mimar dusunuyor...", "yellow"))

        async def on_direct_text(text: str):
            cleaned = (text or "").strip()
            if cleaned:
                self._emit(f"  ↳ {cleaned}")

        try:
            result = await self.base_model.text_query(
                user_text,
                context=context,
                on_direct_text=on_direct_text,
            )
            answer = self._extract_result_text(result)
            self._add_history("assistant", answer)
            self._emit("")
            self._emit(self._color("Mimar>", "green"))
            self._emit(answer)
            self._emit("")
        except Exception as exc:
            self._emit(self._color(f"Model hatasi: {exc}", "red"))
        finally:
            await release_automation("terminal", job_id=job_id)

    async def _request_terminal_approval(self, action_id: str, description: str) -> bool:
        self._emit("")
        self._emit(self._color("ONAY GEREKLI", "yellow"))
        self._emit(f"  {description}")
        try:
            answer = await self._read_line("  Onayliyor musun? [e/H]: ")
        except (EOFError, KeyboardInterrupt):
            return False
        approved = (answer or "").strip().lower() in {"e", "evet", "y", "yes"}
        self.base_model.log_message(
            "sistem",
            f"Terminal onayi: {action_id} -> {'onaylandi' if approved else 'reddedildi'}",
        )
        return approved

    def _build_context(self) -> str:
        selected = self.history[-_MAX_CONTEXT_MESSAGES:]
        rendered = []
        total_chars = 0
        for item in reversed(selected):
            role = "Kullanici" if item.get("role") == "user" else "Asistan"
            line = f"{role}: {item.get('content', '')}"
            if rendered and total_chars + len(line) > _MAX_CONTEXT_CHARS:
                break
            rendered.append(line)
            total_chars += len(line)
        if not rendered:
            return ""
        return "=== TERMINAL KONUSMA GECMISI ===\n" + "\n".join(reversed(rendered)) + "\n\n=== YENI MESAJ ==="

    @staticmethod
    def _extract_result_text(result: Any) -> str:
        if isinstance(result, tuple):
            if len(result) > 1 and str(result[1] or "").strip():
                return str(result[1]).strip()
            if len(result) > 3 and result[3]:
                return str(result[3][-1]).strip()
            if len(result) > 2 and result[2]:
                return str(result[2][-1]).strip()
        if isinstance(result, str) and result.strip():
            return result.strip()
        return "Islem tamamlandi ancak metin yaniti uretilmedi."

    @staticmethod
    def _resolve_switch(action: str, current: bool) -> bool:
        if action in {"on", "ac", "aktif"}:
            return True
        if action in {"off", "kapat", "pasif"}:
            return False
        if action in {"toggle", "degistir"}:
            return not current
        raise ValueError("Durum on, off veya toggle olmali.")

    @staticmethod
    def _format_duration(seconds: int) -> str:
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}s {minutes}dk {secs}sn"
        if minutes:
            return f"{minutes}dk {secs}sn"
        return f"{secs}sn"

    def _load_history(self) -> list[dict]:
        if not os.path.exists(self.history_file):
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, list):
                return []
            return [
                item for item in raw
                if isinstance(item, dict)
                and item.get("role") in {"user", "assistant"}
                and str(item.get("content") or "").strip()
            ][-_MAX_HISTORY:]
        except Exception:
            return []

    def _save_history(self) -> None:
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        temporary = f"{self.history_file}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(self.history[-_MAX_HISTORY:], handle, ensure_ascii=False, indent=2)
            os.replace(temporary, self.history_file)
        except Exception as exc:
            self._emit(self._color(f"Gecmis kaydedilemedi: {exc}", "yellow"))

    def _add_history(self, role: str, content: str) -> None:
        cleaned = (content or "").strip()
        if not cleaned:
            return
        self.history.append(
            {
                "role": role,
                "content": cleaned,
                "time": datetime.now().strftime("%H:%M"),
            }
        )
        self.history = self.history[-_MAX_HISTORY:]
        self._save_history()


async def run_terminal_manager(base_model, *, telegram_enabled: bool = False, discord_enabled: bool = False):
    manager = TerminalManager(
        base_model,
        telegram_enabled=telegram_enabled,
        discord_enabled=discord_enabled,
    )
    await manager.run()

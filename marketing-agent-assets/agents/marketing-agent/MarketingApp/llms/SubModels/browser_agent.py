"""
Browser Agent SubModel — OpenAI-compatible endpoint uzerinde tarayici
tool-calling uzmani.
"""

from __future__ import annotations

import json
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI

from .base import SubModel, SubModelRateLimitError, register_submodel
from MarketingApp.araclar import BROWSER_ARACLARI
from MarketingApp.llms.runtime_config import (
    get_browser_model_name,
    get_browser_reasoning_effort,
    get_model_api_key,
    get_model_api_keys,
    get_openai_compat_base_url,
    get_provider_display_name,
)

load_dotenv()


DEFAULT_SYSTEM_PROMPT = (
    "Sen bir web otomasyon asistansin. Selenium tool'lariyla sayfayi adim adim yonetirsin.\n\n"
    "CALISMA PRENSIPLERI:\n"
    "1. Mevcut sayfa uzerinde calisiyorsan once `browser_ilgili_bolumleri_getir(gorev)` ile goreve en ilgili DOM bolumlerini getir; secim hala belirsizse `browser_dom_oku()` veya `browser_hizli_durum_oku()` ile genislet.\n"
    "2. Gerekiyorsa once `browser_baglan()` dene; bagli tarayici yoksa `browser_baslat()` ile yeni oturum ac.\n"
    "3. Hedef URL'ye `browser_git(url)` ile git.\n"
    "4. Element hedeflerken once semantik araclari tercih et: `browser_bul`, `browser_click_text`, `browser_click_role`, `browser_type_placeholder`.\n"
    "5. `browser_click_id`, `browser_click_css`, `browser_type_id`, `browser_type_css` yalnizca semantik araclar yetmezse kullan.\n"
    "6. Rutin kontrollerde `browser_hizli_durum_oku()` kullan; secim problemi varsa `browser_ilgili_bolumleri_getir()`, detay gerektiginde `browser_dom_oku()` iste.\n"
    "7. Bir arac basarisiz olursa recovery moduna gec: guncel durumu oku, gerekirse kaydir, sekmeleri kontrol et, gerekirse `browser_sekme_degistir()`, bag kopmussa `browser_baglan()` dene.\n"
    "8. Son aksiyonun ardindan gorevi bitti varsayma; en az bir dogrulama araci kullanmadan sonlandirma.\n"
    "9. Gecici olarak tek alt ajan sensin; gorevi baska submodel varmis gibi bolme.\n"
    "10. Gorev tamamlandiginda kisa ve net Turkce ozet ver.\n"
    "11. Tarayiciyi kullanici istemedikce kapatma.\n"
)


class BrowserAgentSubModel(SubModel):
    """Selenium ile web sayfalarinda DOM-tabanli etkilesim uzmani."""

    _FINAL_ACTION_TOOLS = {
        "browser_git",
        "browser_click_id",
        "browser_click_css",
        "browser_click_text",
        "browser_click_role",
        "browser_type_id",
        "browser_type_css",
        "browser_type_placeholder",
        "browser_enter_bas",
        "browser_select_sec",
        "browser_deger_ata",
        "browser_yeni_sekme",
        "browser_sekme_degistir",
        "browser_sekme_kapat",
        "browser_dosya_yukle",
    }

    _VERIFICATION_TOOLS = {
        "browser_hizli_durum_oku",
        "browser_dom_oku",
        "browser_ilgili_bolumleri_getir",
        "browser_eleman_bekle",
        "browser_bul",
        "browser_sekme_listele",
        "browser_screenshot",
    }

    def __init__(self):
        api_keys = get_model_api_keys()
        api_key = api_keys[0] if api_keys else get_model_api_key()
        self.provider_name = get_provider_display_name()
        self.reasoning_effort = get_browser_reasoning_effort()
        if not api_key:
            print(f"⚠️  UYARI: {self.provider_name} API anahtari bulunamadi!")

        super(BrowserAgentSubModel, self).__init__(
            name="browser_agent",
            description=(
                "Web tarayicisini Selenium ile kontrol ederek gezinme, form doldurma, "
                "yorum okuma, yorum gonderme ve DOM tabanli web gorevleri yapan ajan."
            ),
            model_id=get_browser_model_name(),
            api_key=api_key,
            tools=BROWSER_ARACLARI,
        )
        self._configure_openai_client(get_openai_compat_base_url(), api_keys)

    def _extract_message_text(self, message) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return re.sub(r"<thought>.*?</thought>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
                else:
                    maybe_text = getattr(item, "text", None)
                    if maybe_text:
                        texts.append(maybe_text)
            combined = "\n".join(part.strip() for part in texts if part and part.strip()).strip()
            return re.sub(r"<thought>.*?</thought>", "", combined, flags=re.DOTALL | re.IGNORECASE).strip()
        return ""

    def _assistant_message_payload(self, message) -> dict:
        payload = {
            "role": "assistant",
            "content": self._extract_message_text(message),
        }
        tool_calls = []
        for call in getattr(message, "tool_calls", []) or []:
            if isinstance(call, dict):
                call_payload = dict(call)
            elif hasattr(call, "to_dict"):
                call_payload = call.to_dict()
            else:
                call_payload = {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments or "{}",
                    },
                }

            function_payload = call_payload.get("function") or {}
            function_payload["name"] = function_payload.get("name") or call.function.name
            function_payload["arguments"] = function_payload.get("arguments") or call.function.arguments or "{}"
            call_payload["function"] = function_payload
            call_payload["id"] = call_payload.get("id") or call.id
            call_payload["type"] = call_payload.get("type") or "function"
            tool_calls.append(call_payload)
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return payload

    def _parse_tool_args(self, raw_args) -> dict:
        if isinstance(raw_args, dict):
            return raw_args
        if not raw_args:
            return {}
        try:
            return json.loads(raw_args)
        except Exception:
            return {}

    def _truncate_text(self, value, limit: int = 1600) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _tool_failed(self, result) -> bool:
        text = str(result or "").strip()
        lower = text.lower()
        return (
            text.startswith("❌")
            or " başarısız" in lower
            or " basarisiz" in lower
            or "bulunamadı" in lower
            or "bulunamadi" in lower
            or "geçersiz" in lower
            or "gecersiz" in lower
            or "probe hatasi" in lower
        )

    async def _probe_tool(self, name: str, args: dict | None = None) -> str:
        try:
            result = await self._execute_tool(name, args or {})
            return str(result)
        except Exception as e:
            return f"❌ {name} probe hatasi: {e}"

    def _task_needs_existing_page_context(self, gorev: str) -> bool:
        task_text = (gorev or "").lower()
        keywords = (
            "devam",
            "kaldığımız",
            "kaldigimiz",
            "mevcut sayfa",
            "bu sayfa",
            "buradan",
            "şu anki",
            "su anki",
            "sayfayı yenileme",
            "sayfayi yenileme",
            "yenileme",
            "anket",
            "tweet",
            "yorum",
            "formu doldur",
            "bu oturum",
            "same page",
            "current page",
            "continue",
            "resume",
        )
        return any(keyword in task_text for keyword in keywords)

    async def _build_initial_state_summary(self) -> str:
        tab_info = await self._probe_tool("browser_sekme_listele")
        lower_tab_info = tab_info.lower()

        if tab_info.startswith("❌") and ("başlatılmadı" in lower_tab_info or "baslatilmadi" in lower_tab_info):
            dom_info = "Tarayici oturumu henuz acik gorunmuyor."
        else:
            dom_info = await self._probe_tool("browser_hizli_durum_oku")

        return (
            "=== BASLANGIC DURUM KONTROLU ===\n"
            f"Sekmeler:\n{self._truncate_text(tab_info, 1200)}\n\n"
            f"Ilk ekran/DOM durumu:\n{self._truncate_text(dom_info, 2000)}\n"
        )

    async def _build_lightweight_initial_summary(self, gorev: str) -> str:
        if not self._task_needs_existing_page_context(gorev):
            return ""

        tab_info = await self._probe_tool("browser_sekme_listele")
        lower_tab_info = tab_info.lower()
        if tab_info.startswith("❌") and ("başlatılmadı" in lower_tab_info or "baslatilmadi" in lower_tab_info):
            return (
                "=== BASLANGIC DURUM KONTROLU ===\n"
                "Sekmeler:\nTarayici oturumu henuz acik gorunmuyor.\n"
            )

        dom_info = await self._probe_tool(
            "browser_ilgili_bolumleri_getir",
            {"gorev": gorev, "top_k": 2, "komsu_sayisi": 1},
        )
        if dom_info.startswith("❌"):
            dom_info = await self._probe_tool("browser_dom_oku")
        return (
            "=== BASLANGIC DURUM KONTROLU ===\n"
            f"Sekmeler:\n{self._truncate_text(tab_info, 500)}\n\n"
            f"Goreve gore ilgili bolumler:\n{self._truncate_text(dom_info, 1800)}\n"
        )

    async def _build_recovery_message(self, failed_tool_name: str, result) -> str | None:
        if not self._tool_failed(result):
            return None

        result_text = str(result)
        lower_result = result_text.lower()
        lines = [
            f"[SISTEM RECOVERY] `{failed_tool_name}` basarisiz oldu.",
            f"Sonuc: {self._truncate_text(result_text, 700)}",
        ]

        connection_markers = (
            "başlatılmadı",
            "baslatilmadi",
            "disconnected",
            "chrome not reachable",
            "invalid session id",
            "session deleted",
        )
        if any(marker in lower_result for marker in connection_markers):
            reconnect_info = await self._probe_tool("browser_baglan")
            lines.append(f"Yeniden baglan denemesi:\n{self._truncate_text(reconnect_info, 700)}")

        tab_info = await self._probe_tool("browser_sekme_listele")
        lines.append(f"Guncel sekmeler:\n{self._truncate_text(tab_info, 1200)}")

        dom_info = await self._probe_tool("browser_hizli_durum_oku")
        lines.append(f"Guncel DOM:\n{self._truncate_text(dom_info, 2000)}")

        retryable_tools = {
            "browser_bul",
            "browser_click_id",
            "browser_click_css",
            "browser_click_text",
            "browser_click_role",
            "browser_type_id",
            "browser_type_css",
            "browser_type_placeholder",
            "browser_eleman_bekle",
        }
        retryable_markers = (
            "bulunamadı",
            "bulunamadi",
            "not interactable",
            "click intercepted",
            "timeout",
        )
        if failed_tool_name in retryable_tools and any(marker in lower_result for marker in retryable_markers):
            scroll_info = await self._probe_tool("browser_scroll", {"yon": "asagi", "miktar": 500})
            lines.append(f"Otomatik kaydirma denemesi:\n{self._truncate_text(scroll_info, 500)}")
            dom_after_scroll = await self._probe_tool("browser_hizli_durum_oku")
            lines.append(f"Kaydirma sonrasi DOM:\n{self._truncate_text(dom_after_scroll, 2000)}")

        lines.append(
            "Sonraki adimda once guncel duruma gore karar ver; mümkünse "
            "`browser_bul`, `browser_click_text`, `browser_click_role`, "
            "`browser_type_placeholder` gibi semantik araclari tercih et."
        )
        return "\n\n".join(lines)

    def _needs_final_verification(self, tool_name: str, result) -> bool:
        return tool_name in self._FINAL_ACTION_TOOLS and not self._tool_failed(result)

    def _is_verification_tool(self, tool_name: str, result) -> bool:
        return tool_name in self._VERIFICATION_TOOLS and not self._tool_failed(result)

    def _build_final_verification_message(self, last_action_tool: str, partial_response: str) -> str:
        response_hint = self._truncate_text(partial_response, 600) if partial_response else "(yok)"
        return (
            "[SISTEM DEVAM UYARISI] Son aksiyondan sonra gorev dogrulanmadan durma.\n\n"
            f"Son aksiyon: `{last_action_tool}`\n"
            f"Mevcut kismi ozet: {response_hint}\n\n"
            "Simdi once son adimin gercekten tamamlandigini dogrula. "
            "Bunun icin `browser_dom_oku`, `browser_eleman_bekle`, `browser_bul` veya "
            "`browser_sekme_listele` gibi bir dogrulama araci kullan. "
            "Dogrulama basariliysa gorevi bitir; degilse eksik son adimi tamamla."
        )

    async def run(self, gorev: str) -> str:
        print(f"\n🌐 [{self.name}] Gorev baslatiliyor: {gorev[:100]}...")

        from MarketingApp.araclar import rol_oku
        aktif_rol = rol_oku()

        system_prompt = DEFAULT_SYSTEM_PROMPT

        if not aktif_rol.startswith("⚠️") and not aktif_rol.startswith("❌"):
            system_prompt += (
                "\n=========== MARKETING KISILIGI (ZORUNLU) ===========\n"
                f"{aktif_rol}\n"
                "===================================================\n"
            )

        initial_state_summary = await self._build_lightweight_initial_summary(gorev)
        user_content = gorev
        if initial_state_summary:
            user_content = (
                f"{gorev}\n\n"
                f"{initial_state_summary}\n"
                "Bu baslangic bilgisine gore ilk en guvenli adimi sec."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        final_response = "Tamamlandi"
        pending_final_verification = False
        last_action_tool = ""
        verification_reminders_sent = 0

        try:
            for _ in range(24):
                create_kwargs = {
                    "model": self.model_id,
                    "messages": messages,
                    "tools": self._build_tool_schemas(),
                    "tool_choice": "auto",
                }
                if self.reasoning_effort:
                    create_kwargs["reasoning_effort"] = self.reasoning_effort

                completion = await self._create_chat_completion_with_failover(create_kwargs)
                message = completion.choices[0].message
                current_text = self._extract_message_text(message)
                tool_calls = getattr(message, "tool_calls", None) or []

                if tool_calls:
                    messages.append(self._assistant_message_payload(message))
                    if current_text:
                        final_response = current_text

                    for call in tool_calls:
                        args = self._parse_tool_args(call.function.arguments)
                        result = await self._execute_tool(call.function.name, args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.function.name,
                            "content": json.dumps({"result": str(result)[:8000]}, ensure_ascii=False),
                        })
                        if self._needs_final_verification(call.function.name, result):
                            pending_final_verification = True
                            last_action_tool = call.function.name
                        elif self._is_verification_tool(call.function.name, result):
                            pending_final_verification = False
                            verification_reminders_sent = 0
                        recovery_message = await self._build_recovery_message(call.function.name, result)
                        if recovery_message:
                            messages.append({"role": "user", "content": recovery_message})
                    continue

                if current_text:
                    final_response = current_text
                if pending_final_verification and verification_reminders_sent < 2:
                    messages.append({
                        "role": "user",
                        "content": self._build_final_verification_message(last_action_tool, current_text or final_response),
                    })
                    verification_reminders_sent += 1
                    continue
                break

        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "limit" in err.lower():
                print(f"  ⚠️ [{self.name}] {self.provider_name} limit hatasi! BaseModel'e devrediliyor.")
                raise SubModelRateLimitError(self.name, self.tools)
            print(f"  ❌ [{self.name}] API Hatasi: {e}")
            return f"Browser Agent Hatasi: {e}"

        print(f"  ✅ [{self.name}] Gorev tamamlandi.")
        return final_response


register_submodel(BrowserAgentSubModel())

"""
Content Creator Agent SubModel — medya arama, brief ve içerik üretim uzmanı.
"""

from __future__ import annotations

import json
import re

from openai import AsyncOpenAI

from .base import SubModel, SubModelRateLimitError, register_submodel
from MarketingApp.araclar import CONTENT_CREATOR_ARACLARI
from MarketingApp.llms.runtime_config import (
    get_model_api_key,
    get_model_api_keys,
    get_openai_compat_base_url,
    get_provider_display_name,
    get_submodel_model_name,
    get_submodel_reasoning_effort,
)


DEFAULT_SYSTEM_PROMPT = (
    "Sen yaratıcı bir content creator ajansın. Görevin; verilen brief'ten yüksek kaliteli "
    "içerik fikirleri, metinler ve medya seçenekleri çıkarmaktır.\n\n"
    "CALISMA PRENSIPLERI:\n"
    "1. Platform aksiyonu yapma, paylaşım yapma veya kullanıcı adına yayınlama. Yalnızca üret, ara ve raporla.\n"
    "2. Kullanıcı URL verirse veya web sitesinden içerik çıkarma isterse önce `website_icerik_cikar` kullan.\n"
    "2b. Web sitesini doğrudan sosyal medya içeriğine çevirmek gerekirse `website_iceriginden_post_paketi_uret` kullan.\n"
    "3. Görsel veya video stok medya gerekiyorsa Pexels araçlarını kullan.\n"
    "4. Fotoğraf araması için `pexels_fotograf_ara`, seçkiler için `pexels_curated_fotograflar`, "
    "tekil detay için `pexels_fotograf_detay` kullan.\n"
    "5. Video araması için `pexels_video_ara`, popüler videolar için `pexels_populer_videolar` kullan.\n"
    "6. Kullanıcı Reels, Shorts, TikTok, stok videolu video veya MP4 çıktı isterse "
    "`video_post_olustur_ve_mp4_kaydet` aracını kullan.\n"
    "7. Kullanıcı görselli post, afiş, kapak, X/Instagram/LinkedIn postu veya PNG çıktı isterse "
    "`html_css_post_olustur_ve_png_kaydet` aracını kullan; sadece metin veya plan yazmakla yetinme.\n"
    "8. HTML/CSS post veya MP4 üretirken başlık, alt başlık, CTA, platform, boyut, renk ve stok medya sorgusunu "
    "brief'e göre sen belirleyebilirsin.\n"
    "9. Pexels sonucu önerirken fotoğrafçı/video sahibi adını, Pexels URL'sini ve uygun medya URL'sini belirt.\n"
    "10. İçerik üretirken hedef, kitle, ton, format ve CTA'yı netleştir.\n"
    "11. Klişe, spam, boş ve tekrar eden içerikten kaçın.\n"
    "12. Brief sosyal medya, kampanya veya onceki islerle ilgiliyse once `context_paketi_oku` ile canlı hafıza paketini oku; tum workspace'i modele yigma.\n"
    "13. Caption, fikir paketi, medya secimi, PNG veya MP4 uretimi tamamlaninca `context_aksiyon_kaydet` ile hangi dosya/konu/aci uretildigini recent_actions'a kaydet.\n"
    "14. PNG/MP4 ürettiysen final yanıtta mutlak dosya yolunu, ara dosyaların silinip silinmediğini ve kullanılan stok medya bilgisini yaz.\n"
    "15. Website paketi ürettiysen workspace markdown yolunu ve kaynak URL'yi yaz.\n"
    "16. Son yanıtta hangi website/Pexels/post/video tool'larını kullandığını kısa özetle.\n"
    "17. Yanıtlarını Türkçe ver.\n"
)


class ContentCreatorAgentSubModel(SubModel):
    """Caption, kreatif brief, görsel/video medya arama ve içerik paketleme uzmanı."""

    def __init__(self):
        api_keys = get_model_api_keys()
        api_key = api_keys[0] if api_keys else get_model_api_key()
        self.provider_name = get_provider_display_name()
        self.reasoning_effort = get_submodel_reasoning_effort()
        if not api_key:
            print(f"⚠️  UYARI: {self.provider_name} API anahtari bulunamadi!")

        super(ContentCreatorAgentSubModel, self).__init__(
            name="content_creator_agent",
            description=(
                "Icerik uretim ve medya arama uzmani. Caption, thread, carousel akisi, "
                "kreatif kampanya fikri, thumbnail brief'i, video storyboard'i, Pexels "
                "uzerinden stok fotograf/video arama, verilen web sitesinden icerik cikarip "
                "post paketine donusturme, HTML/CSS ile PNG post uretme ve stok videolu MP4 "
                "sosyal medya videosu olusturma "
                "gorevleri icin bu ajani kullan. Platformda paylasim yapmaz; uygun medya "
                "seceneklerini, kaynak linklerini, PNG/MP4 dosya yolunu ve kullanilabilir "
                "icerik metinlerini hazirlar."
            ),
            model_id=get_submodel_model_name(),
            api_key=api_key,
            tools=CONTENT_CREATOR_ARACLARI,
        )
        self._configure_openai_client(get_openai_compat_base_url(), api_keys)

    def _strip_thought_blocks(self, text: str) -> str:
        return re.sub(r"<thought>.*?</thought>", "", text or "", flags=re.DOTALL | re.IGNORECASE).strip()

    def _extract_message_text(self, message) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return self._strip_thought_blocks(content)
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
                else:
                    maybe_text = getattr(item, "text", None)
                    if maybe_text:
                        texts.append(maybe_text)
            return self._strip_thought_blocks("\n".join(part.strip() for part in texts if part and part.strip()))
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

    async def run(self, gorev: str) -> str:
        print(f"\n🎨 [{self.name}] Icerik uretim gorevi baslatiliyor: {gorev[:120]}...")

        from MarketingApp.araclar import rol_oku

        aktif_rol = rol_oku()
        system_prompt = DEFAULT_SYSTEM_PROMPT
        if not aktif_rol.startswith("⚠️") and not aktif_rol.startswith("❌"):
            system_prompt += (
                "\n=========== MARKETING KISILIGI (ZORUNLU) ===========\n"
                f"{aktif_rol}\n"
                "===================================================\n"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": gorev},
        ]
        final_response = "Tamamlandi"

        try:
            for _ in range(16):
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
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "name": call.function.name,
                                "content": json.dumps({"result": str(result)[:6000]}, ensure_ascii=False),
                            }
                        )
                    continue

                if current_text:
                    final_response = current_text
                break
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "limit" in err.lower():
                print(f"  ⚠️ [{self.name}] {self.provider_name} limit hatasi! BaseModel'e devrediliyor.")
                raise SubModelRateLimitError(self.name, self.tools)
            print(f"  ❌ [{self.name}] API Hatasi: {e}")
            return f"Content Creator Agent Hatasi: {e}"

        print(f"  ✅ [{self.name}] Gorev tamamlandi.")
        return final_response


register_submodel(ContentCreatorAgentSubModel())

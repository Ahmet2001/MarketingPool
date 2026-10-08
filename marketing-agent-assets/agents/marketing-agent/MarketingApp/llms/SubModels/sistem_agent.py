"""
Sistem Agent SubModel — Dosya yönetimi, sistem analizi ve kendini geliştirme uzmanı.
Güçlü terminal + dosya + workspace araçlarıyla karmaşık sistem görevlerini yönetir.
llama-3.3-70b-versatile modeli üzerinde çalışır.
"""

import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
import asyncio
from .base import SubModel, register_submodel, SubModelRateLimitError
from MarketingApp.araclar import SISTEM_ARACLARI

load_dotenv()

class SistemAgentSubModel(SubModel):
    """Dosya sistemi yönetimi, workspace, sistem analizi ve yeni araç geliştirme uzmanı."""

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("⚠️  UYARI: GEMINI_API_KEY .env dosyasında bulunamadı!")
        super().__init__(
            name="sistem_agent",
            description=(
                "Sistem yönetimi, dosya işlemleri ve kendini geliştirme uzmanı. "
                "Dosya okuma/yazma/listeleme/silme, workspace yönetimi, görüntü işleme, "
                "sistem durumu analizi ve yeni araç (tool) geliştirme görevleri için kullan. "
                "Karmaşık çok adımlı sistem görevlerini, proje dosyası düzenlemeyi, "
                "ya da sistemin yeni yetenekler kazanmasını gerektiren işlemler için idealdir."
            ),
            model_id="gemini-2.5-flash-native-audio-latest",
            api_key=api_key,
            tools=SISTEM_ARACLARI,
        )
        self._client = genai.Client(api_key=self.api_key)

    async def run(self, gorev: str) -> str:
        """Sistem görevini tool-calling loop ile çalıştırır (Gemini Live API)."""
        print(f"\n🖥️  [{self.name}] Görev alındı: {gorev[:100]}...")

        sys_prompt = (
            "Sen güçlü bir sistem yöneticisi ajanısın. Sistem ortamın Windows'tur (Komutları CMD/PowerShell için üret). Tümüyle yetkilisin, `sudo` kullanmana gerek yoktur.\n"
            "Görevlerin:\n"
            "- Dosya sistemi üzerinde okuma, yazma, listeleme, silme işlemleri\n"
            "- Terminal komutlarıyla sistem analizi ve otomasyon\n"
            "- Görüntü işleme ve dönüştürme işlemleri\n"
            "- Sisteme yeni araçlar (Python modülleri) yazıp kaydetme\n\n"
            "MİMARAİ OFİSİ VE BELLEK KURALLARI:\n"
            "1. Çalışma alanın 'workspace' dizinidir. Tüm yeni scriptleri mutlak suretle 'workspace/code/' klasörüne kaydet.\n"
            "2. 'targets/' klasörü kullanıcının yüklediği ham kaynaklardır (MUTLAKA DİKKATE AL). 'drafts/' taslaklar içindir.\n"
            "3. Sistem hakkında kalıcı belleğe yazılması gereken mimari kuralları 'bellek_yaz' ile 'notlar' kategorisine kaydet.\n"
            "Karmaşık görevlerde önce analiz yap, sonra adım adım ilerle. Yanıtını Türkçe ver."
        )

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
                )
            ),
            system_instruction=sys_prompt,
            tools=self.tools,
        )

        final_response = "[SistemAgent yanıt üretemedi]"
        
        try:
            async with self._client.aio.live.connect(
                model=self.model_id,
                config=config
            ) as session:
                
                await session.send(input=gorev, end_of_turn=True)
                
                async for message in session.receive():
                    if message.server_content and message.server_content.model_turn:
                        for part in message.server_content.model_turn.parts:
                            if part.text:
                                final_response = part.text
                                
                    if message.tool_call:
                        for call in message.tool_call.function_calls:
                            name = call.name
                            args = dict(call.args) if call.args else {}
                            
                            result = await self._execute_tool(name, args)
                            
                            # Tool yanıtını Live API objesiyle geri gönder
                            tool_response = types.LiveClientToolResponse(
                                function_responses=[types.FunctionResponse(
                                    name=name, id=call.id,
                                    response={"result": str(result)[:8000]}
                                )]
                            )
                            await session.send(input=tool_response)
                            print(f"  🔄 [{self.name}] Sistem aracı çalıştırıldı: {name}")
            
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower() or "limit" in str(e).lower():
                print(f"  ⚠️ [{self.name}] Gemini Limit Hatası! BaseModel'e devrediliyor.")
                raise SubModelRateLimitError(self.name, self.tools)
            print(f"  ❌ [{self.name}] Live API Hatası: {e}")
            raise e

        print(f"  ✅ [{self.name}] Görev tamamlandı.")
        return final_response

# Modül import edildiğinde otomatik kayıt
register_submodel(SistemAgentSubModel())

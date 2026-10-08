"""
Araştırma Agent SubModel — Derinlemesine web araştırması ve rapor yazma uzmanı.
Birden fazla web araması yaparak bilgileri sentezler ve kapsamlı raporlar üretir.
"""

import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from .base import SubModel, register_submodel, SubModelRateLimitError
from MarketingApp.araclar import ARAMA_ARACLARI

load_dotenv()

class ArastirmaAgentSubModel(SubModel):
    """Web araştırması, haber takibi ve kapsamlı rapor yazma uzmanı."""

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("⚠️  UYARI: GEMINI_API_KEY .env dosyasında bulunamadı!")
        super().__init__(
            name="arastirma_agent",
            description=(
                "Derinlemesine web araştırması ve kapsamlı rapor yazma uzmanı. "
                "Birden fazla farklı açıdan web araması yaparak bilgileri toplar, "
                "sentezler ve yapılandırılmış Türkçe raporlar üretir. "
                "Güncel haberler, teknoloji araştırması, fiyat karşılaştırması, "
                "konu özeti veya herhangi bir bilgi derleme görevi için kullan."
            ),
            model_id="gemini-2.5-flash-native-audio-latest",
            api_key=api_key,
            tools=ARAMA_ARACLARI,
        )
        self._client = genai.Client(api_key=self.api_key)

    async def run(self, gorev: str) -> str:
        """Araştırma görevini Gemini Live API üzerinden çalıştırır."""
        print(f"\n🔍 [{self.name}] Araştırma görevi alındı: {gorev[:100]}...")

        sys_prompt = (
            "Sen kapsamlı bir araştırma asistanısın. Görevin:\n"
            "1. Verilen konuyu birden fazla farklı arama sorgusuyla araştır\n"
            "2. Toplanan bilgileri workspace'e ara sonuç olarak kaydet\n"
            "3. Tüm bilgileri sentezleyerek yapılandırılmış, kapsamlı bir rapor oluştur\n"
            "4. Raporu hem workspace'e kaydet hem de doğrudan yanıt olarak sun\n\n"
            "MİMARAİ OFİSİ VE BELLEK KURALLARI:\n"
            "1. 'workspace/targets/' klasörü kullanıcının araştırma için verdiği ham kaynaklardır. Aramalara başlamadan önce burayı kontrol et.\n"
            "2. Araştırma sonuçlarını 'workspace/drafts/' klasörüne taslak olarak, nihai raporları 'workspace/reports/' klasörüne yaz.\n"
            "3. Kullanıcının araştırma stili tercihlerini 'bellek_oku' ile 'tercihler' kategorisinden öğren.\n"
            "UYUM VE SEBAT KURALI: Kullanıcının istediği bilgiye ulaşmak için tüm yolları (farklı aramalar, farklı URL'ler) dene. "
            "Hemen 'Bulamadım' diyerek pes etme. Yanıtını Türkçe ver.\n"
            "Raporlarını Türkçe yaz. Kaynakları belirt. Başlıklar, maddeler ve açıklamalarla düzenli bir format kullan."
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

        final_response = "[ArastirmaAgent yanıt üretemedi]"

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

                            tool_response = types.LiveClientToolResponse(
                                function_responses=[types.FunctionResponse(
                                    name=name, id=call.id,
                                    response={"result": str(result)[:2000]}
                                )]
                            )
                            await session.send(input=tool_response)
                            print(f"  🔄 [{self.name}] Araştırma aracı: {name}")

        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower() or "limit" in str(e).lower():
                print(f"  ⚠️ [{self.name}] Rate limit! BaseModel'e devrediliyor.")
                raise SubModelRateLimitError(self.name, self.tools)
            print(f"  ❌ [{self.name}] Live API Hatası: {e}")
            raise e

        print(f"  ✅ [{self.name}] Araştırma tamamlandı.")
        return final_response

# Modül import edildiğinde otomatik kayıt
register_submodel(ArastirmaAgentSubModel())

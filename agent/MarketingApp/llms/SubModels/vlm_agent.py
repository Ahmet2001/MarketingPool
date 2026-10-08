"""
VLM Agent SubModel — Ekran, klavye ve fare kontrol uzmanı.
gemini-2.5-flash-native-audio-latest modeli üzerinde çalışır.

v2: Güçlü Self-Correction (Oto-Doğrulama) sistemi.
"""

import os
import json
import asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types
from .base import SubModel, register_submodel
from MarketingApp.araclar import VLM_ARACLARI, get_screenshot_bytes

load_dotenv()

class VLMAgentSubModel(SubModel):
    """Ekran yakalama, fare ve klavye kontrol uzmanı."""

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("⚠️  UYARI: GEMINI_API_KEY .env dosyasında bulunamadı!")
        
        super(VLMAgentSubModel, self).__init__(
            name="vlm_agent",
            description=(
                "Bilgisayarın ekranını görme (screenshot), fareyi hareket ettirme/tıklama "
                "ve klavye ile metin yazma uzmanı. Ekranı inceleyip bir butona tıklamak, "
                "bir metin kutusuna yazı yazmak veya sayfayı kaydırmak gibi görsel "
                "ve etkileşimli görevler için bu ajanı kullan."
            ),
            model_id="gemini-2.5-flash-native-audio-latest",
            api_key=api_key,
            tools=VLM_ARACLARI,
        )
        self._client = genai.Client(api_key=self.api_key)

    async def run(self, gorev: str, image_bytes: bytes = None) -> str:
        """Kullanıcının çalışan yöntemiyle (Multimodal List) VLM görevini icra eder."""
        print(f"\n📸 [{self.name}] Görev (Native Multimodal) başlatılıyor: {gorev[:100]}...")

        # 1. ADIM: Live API Yapılandırması
        grid_info = (
            "Ekran üzerinde yüksek hassasiyetli ızgara (High-Precision Grid) sistemi mevcuttur:\n"
            "- Kırmızı çizgiler ve etiketler 50 birimlik ANA bölmeleri gösterir.\n"
            "- İnce ve şeffaf kırmızı çizgiler 10 birimlik HASSAS bölmeleri gösterir.\n"
            "- Hedefleme yaparken bu 10'luk çizgileri referans alarak milimetrik isabet sağla."
        ) if not image_bytes else "Sana gönderilen bu resmi analiz et."
        
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
                )
            ),
            system_instruction=(
                f"Sen bir VLM asistanısın. Sana gönderilen görseli rehber alarak görevi yerine getir.\n"
                f"ÖNEMLİ: {grid_info} Tüm etkileşimler için bu görseli temel al.\n"
                "KAYDIRMA (SCROLL) YETENEĞİ:\n"
                "- Sayfayı aşağı indirmek için `scroll_down(amount=500)` aracını kullan.\n"
                "- Sayfayı yukarı çıkarmak için `scroll_up(amount=500)` aracını kullan.\n"
                "MİKROSKOP YETENEĞİ:\n"
                "- Eğer ekrandaki bir yazıyı okumakta zorlanıyorsan veya bir butonu/ikonu net göremiyorsan `look_closer(x, y)` aracını kullan.\n"
                "- Tıklamadan ÖNCE emin olmak istiyorsan `hover_mouse(x, y)` aracıyla fareyi o noktaya götür.\n"
                "- Belirli bir pikselin rengini kontrol etmek istersen `get_pixel_color(x, y)` kullan.\n"
                "MİMARAİ OFİSİ VE BELLEK (ZORUNLU):\n"
                "- Kullanıcının analiz etmeni istediği ekran görüntüleri, referans tasarımlar veya UI görselleri 'workspace/targets/' klasöründe bulunabilir. Bu dosyaları referans al.\n"
                "- Ekrandan elde ettiğin önemli metinleri, kalıcı verileri, UI renk kodları gibi bilgileri 'bellek_yaz' aracıyla uzun vadeli belleğe kaydet.\n"
                "KENDİ KENDİNİ DOĞRULAMA (ZORUNLU!):\n"
                "- Her `click_mouse`, `type_text`, `press_key` veya `hover_mouse` işleminden sonra SİSTEM SANA EKRANIN GÜNCEL HALİNİ OTOMATİK GÖNDERİR.\n"
                "- Yeni fotoğrafı MUTLAKA DİKKATLİCE İNCELE. Ekranda gerçekten bir değişiklik oldu mu kontrol et.\n"
                "- ASLA körü körüne 'yaptım' deme. Gözlerinle (yeni ekran görüntüsüyle) doğrulamadan bir adımı tamamlanmış sayma.\n"
                "- Eğer yeni ekran görüntüsünde HİÇBİR DEĞİŞİKLİK YOKSA, o zaman tıklaman BAŞARISIZ olmuştur. Koordinatı değiştirerek tekrar dene.\n"
                "- Eğer yanlış yere tıkladıysan (beklenmeyen bir menü açıldıysa), ESC tuşuna bas ve tekrar dene.\n"
                "TIKLAMA STRATEJİSİ:\n"
                "- Bir butona tıklamadan önce butonun ORTASINI hedefle.\n"
                "- Küçük butonlar için önce `look_closer` ile yakınlaştır, kesin koordinatı öğren.\n"
                "- Her tıklamadan sonra 'Ekranda ne değişti?' diye kendine sor ve bunu yeni ekran görüntüsünden kontrol et.\n"
                "UYUM VE SEBAT KURALI:\n"
                "- Kullanıcının isteğini ileride SMS veya E-posta onayı gelecek diye ASLA reddetme.\n"
                "- O aşamaya gelene kadar tüm formları doldur. Onay ekranına geldiğinde kullanıcıya 'Kod bekleniyor' bilgisini ver.\n"
                "- Görevin TAMAMEN ve GÖRSEL OLARAK doğrulanmış şekilde BİTTİĞİNDEN eminsen 'yaptım' de. Emin değilsen devam et."
            ),
            tools=self.tools,
        )

        # Varsayılan yanıt artık "belirsiz" — model açıkça "yaptım" demeli
        final_response = "[VLM Agent görevi işledi ancak açık bir sonuç bildirmedi]"
        try:
            # 2. ADIM: Live Bağlantısı ve Tek Seferlik Multimodal Gönderim
            async with self._client.aio.live.connect(
                model=self.model_id,
                config=config
            ) as session:
                
                # Resim yoksa ekran görüntüsü al
                img_to_send = image_bytes if image_bytes else get_screenshot_bytes(add_grid=True)
                
                # Kullanıcının onayladığı çalışan liste formatı (Resim + Görev)
                await session.send(
                    input=[
                        types.Part(
                            inline_data=types.Blob(
                                data=img_to_send,
                                mime_type="image/jpeg"
                            )
                        ),
                        gorev
                    ],
                    end_of_turn=True
                )
                print(f"  ✅ [{self.name}] Multimodal veri gönderildi. Yanıt bekleniyor...")

                # 3. ADIM: Yanıt ve Tool Call Döngüsü
                aksiyon_araclari = [
                    "click_mouse", "type_text", "press_key", 
                    "scroll_up", "scroll_down", 
                    "double_click_mouse", "right_click_mouse", "hover_mouse"
                ]
                
                # Son yapılan aksiyonu takip et (doğrulama mesajında kullan)
                son_aksiyon = None
                son_aksiyon_args = None
                
                async for message in session.receive():
                    if message.server_content and message.server_content.model_turn:
                        for part in message.server_content.model_turn.parts:
                            if part.text:
                                final_response = part.text
                                
                    if message.tool_call:
                        needs_auto_screenshot = False
                        
                        for call in message.tool_call.function_calls:
                            name = call.name
                            args = dict(call.args) if call.args else {}
                            
                            # Tool'u çalıştır (Asenkron bekleyerek!)
                            result = await self._execute_tool(name, args)
                            
                            if name in aksiyon_araclari:
                                needs_auto_screenshot = True
                                son_aksiyon = name
                                son_aksiyon_args = args
                            
                            # EĞER EKRAN GÖRÜNTÜSÜ VEYA ZOOM ALINDIYSA: Vizyonu güncelle (Enjeksiyon)
                            if name in ["get_screenshot_bytes", "look_closer"] and isinstance(result, bytes):
                                # 1. Önce tool yanıtını gönder (sembolik metin)
                                desc = "İstediğin bölgeye ait yakın çekim (zoom) görüntüsü" if name == "look_closer" else "Ekranın güncel genel görüntüsü"
                                tool_response = types.LiveClientToolResponse(
                                    function_responses=[types.FunctionResponse(
                                        name=name, id=call.id,
                                        response={"result": f"{desc} aşağıdadır."}
                                    )]
                                )
                                await session.send(input=tool_response)
                                
                                # 2. Hemen ardından YENİ GÖRÜNTÜYÜ vizyon partı olarak gönder
                                await session.send(
                                    input=[
                                        types.Part(
                                            inline_data=types.Blob(
                                                data=result,
                                                mime_type="image/jpeg"
                                            )
                                        ),
                                        f"İşte {desc}. Lütfen bu yeni görüntüyü dikkatlice incele ve işlemlerine devam et."
                                    ],
                                    end_of_turn=not needs_auto_screenshot
                                )
                                print(f"  📸 [{self.name}] Yeni vizyon verisi ({name}) oturuma enjekte edildi.")
                                # Vizyon zaten gönderildi, auto-screenshot'a gerek yok
                                needs_auto_screenshot = False
                            else:
                                # Normal Tool Yanıtı
                                tool_response = types.LiveClientToolResponse(
                                    function_responses=[types.FunctionResponse(
                                        name=name, id=call.id,
                                        response={"result": str(result)[:2000]}
                                    )]
                                )
                                await session.send(input=tool_response)

                        # ══════════════════════════════════════════════════════════
                        # OTO-DOĞRULAMA: Aksiyon yapıldıysa yeni ekran al ve
                        # modeli zorunlu doğrulamaya tabi tut
                        # ══════════════════════════════════════════════════════════
                        if needs_auto_screenshot:
                            await asyncio.sleep(1.5)  # Animasyon/Yükleme payı
                            new_img = get_screenshot_bytes(add_grid=True)
                            
                            # Aksiyona özel doğrulama sorusu oluştur
                            if son_aksiyon == "click_mouse":
                                dogrulama = (
                                    f"Az önce ({son_aksiyon_args.get('x', '?')}, {son_aksiyon_args.get('y', '?')}) koordinatına tıkladın. "
                                    "Yukarıdaki GÜNCEL ekran görüntüsünü DİKKATLİCE incele:\n"
                                    "1. Ekranda bir değişiklik oldu mu? (Yeni sayfa açıldı mı, menü belirdi mi, buton aktif oldu mu?)\n"
                                    "2. Eğer ekran AYNI KALDIYSA → Tıklaman BAŞARISIZ. Koordinatı değiştirerek tekrar dene.\n"
                                    "3. Eğer bir değişiklik varsa → Değişiklik beklediğin şey mi? İstediğin butona/linke mi tıklanmış?\n"
                                    "4. Doğrulama sonucuna göre ya düzelt ya da planındaki bir sonraki adıma geç."
                                )
                            elif son_aksiyon == "type_text":
                                dogrulama = (
                                    "Az önce bir metin yazdın. Yukarıdaki GÜNCEL ekran görüntüsünü DİKKATLİCE incele:\n"
                                    "1. Yazdığın metin ekranda göründü MÜ? Input kutusunda metni görebiliyor musun?\n"
                                    "2. Eğer metin görünmüyorsa → Yanlış yere yazılmış olabilir. Önce doğru input'a tıkla, sonra tekrar yaz.\n"
                                    "3. Doğrulama sonucuna göre ya düzelt ya da bir sonraki adıma geç."
                                )
                            else:
                                dogrulama = (
                                    f"Az önce `{son_aksiyon}` işlemini yaptın. Yukarıdaki GÜNCEL ekran görüntüsünü incele:\n"
                                    "Ekranda beklenen değişiklik gerçekleşti mi? Gerçekleşmediyse tekrar dene. "
                                    "Gerçekleştiyse bir sonraki adıma geç."
                                )
                            
                            await session.send(
                                input=[
                                    types.Part(
                                        inline_data=types.Blob(
                                            data=new_img,
                                            mime_type="image/jpeg"
                                        )
                                    ),
                                    dogrulama
                                ],
                                end_of_turn=True
                            )
                            print(f"  📸 [{self.name}] Oto-doğrulama: {son_aksiyon} sonrası yeni görüntü + soru enjekte edildi.")

        except Exception as e:
            print(f"  ❌ [{self.name}] Live API Hatası: {e}")
            return f"VLM Hatası: {e}"

        print(f"  ✅ [{self.name}] Görev tamamlandı.")
        return final_response

# Modül import edildiğinde otomatik kayıt
register_submodel(VLMAgentSubModel())

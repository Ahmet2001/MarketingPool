"""
VLM Araçları — Ekran yakalama, fare ve klavye kontrolü.
"""

import os
import datetime
import mss
import mss.tools
import psutil
from PIL import Image
import io

try:
    import pyautogui
    _PYAUTOGUI_IMPORT_ERROR = None
except BaseException as pyautogui_import_error:
    pyautogui = None
    _PYAUTOGUI_IMPORT_ERROR = pyautogui_import_error

from MarketingApp.paths import workspace_path

# Workspace dizini (varsayilan: proje kok dizini; MIMAR_WORKSPACE_DIR ile override edilebilir)
_WORKSPACE_SCREENSHOTS = workspace_path("screenshots")

# Global bot instance (tg_bot.py tarafından set edilir)
_BOT_INSTANCE = None
_LAST_CHAT_ID = None


def _require_pyautogui():
    if pyautogui is None:
        raise RuntimeError(
            "pyautogui kullanilamiyor. Sistem GUI paketleri eksik olabilir "
            f"(orijinal hata: {_PYAUTOGUI_IMPORT_ERROR})."
        )
    return pyautogui

def register_bot(bot, chat_id=None):
    global _BOT_INSTANCE, _LAST_CHAT_ID
    _BOT_INSTANCE = bot
    if chat_id:
        _LAST_CHAT_ID = chat_id


def get_registered_bot():
    """Kayitli Telegram bot instance'ini ve son chat_id'yi dondurur."""
    return _BOT_INSTANCE, _LAST_CHAT_ID

def _ensure_screenshots_dir():
    """Screenshots dizininin var olduğundan emin olur."""
    os.makedirs(_WORKSPACE_SCREENSHOTS, exist_ok=True)

def get_system_status() -> str:
    """Sistem CPU ve RAM durumunu döndürür."""
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    return f"CPU Kullanımı: %{cpu}, RAM Kullanımı: %{ram.percent} ({ram.used / (1024**3):.1f}GB / {ram.total / (1024**3):.1f}GB)"

async def _send_screenshot_to_telegram(image_bytes, path):
    """Resmi Telegram'a asenkron gönderir."""
    if _BOT_INSTANCE and _LAST_CHAT_ID:
        try:
            import io
            await _BOT_INSTANCE.send_photo(
                chat_id=_LAST_CHAT_ID,
                photo=io.BytesIO(image_bytes),
                caption=f"📸 Ekran görüntüsü alındı.\n📍 `{path}`"
            )
        except Exception as e:
            print(f"⚠️ Screenshot gönderilemedi: {e}")

def take_screenshot() -> str:
    """Bilgisayarın o anki ekran görüntüsünü alır ve workspace/screenshots klasörüne kaydeder."""
    try:
        _ensure_screenshots_dir()
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Birinci ekran
            sct_img = sct.grab(monitor)
            raw_png = mss.tools.to_png(sct_img.rgb, sct_img.size)

        # Tarih-saat damgalı dosya adıyla kaydet
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        save_path = os.path.join(_WORKSPACE_SCREENSHOTS, filename)
        with open(save_path, "wb") as f:
            f.write(raw_png)

        # Telegram'a gönder (Arka planda)
        if _BOT_INSTANCE:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(_send_screenshot_to_telegram(raw_png, save_path))
            except Exception as e:
                print(f"Async Task Hatası: {e}")

        return f"Ekran görüntüsü alındı ve '{save_path}' konumuna kaydedildi. Kullanıcıya Telegram üzerinden gönderildi."
    except Exception as e:
        return f"Ekran görüntüsü alınamadı: {e}"

from PIL import Image, ImageDraw, ImageFont

def get_screenshot_bytes(add_grid: bool = False) -> bytes:
    """Ekranın anlık görüntüsünü JPEG formatında bytes olarak döndürür. opsiyonel olarak ızgara ekler.
    
    Args:
        add_grid: Ekrana tıklama için referans ızgarası eklenip eklenmeyeceği.
    """
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        
        # PIL Image formatına dönüştür
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        
        if add_grid:
            # Şeffaf katman desteği için RGBA'ya çevir
            img = img.convert("RGBA")
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            w, h = img.size
            
            # 1. Minor Izgara (Her 10 birimde bir - Daha Şeffaf)
            for i in range(0, 1010, 10):
                x_pos = int(round(i * w / 1000))
                if x_pos >= w: x_pos = w - 1
                # %15 şeffaflık (40/255)
                color = (255, 0, 0, 40) if i % 50 != 0 else (255, 0, 0, 100)
                draw.line([(x_pos, 0), (x_pos, h)], fill=color, width=1)
                
                y_pos = int(round(i * h / 1000))
                if y_pos >= h: y_pos = h - 1
                draw.line([(0, y_pos), (w, y_pos)], fill=color, width=1)

            # 2. Major Izgara (Her 50 birimde bir - Daha Belirgin)
            for i in range(0, 1050, 50):
                x_pos = int(round(i * w / 1000))
                if x_pos >= w: x_pos = w - 1
                # %50 şeffaflık (130/255)
                major_color = (255, 0, 0, 130)
                draw.line([(x_pos, 0), (x_pos, h)], fill=major_color, width=1)
                draw.text((x_pos + 2, 2), str(i), fill=(255, 0, 0, 200)) # Etiketler daha okunaklı
                
                y_pos = int(round(i * h / 1000))
                if y_pos >= h: y_pos = h - 1
                draw.line([(0, y_pos), (w, y_pos)], fill=major_color, width=1)
                draw.text((2, y_pos + 2), str(i), fill=(255, 0, 0, 200))

            # Katmanları birleştir ve RGB'ye (JPEG için) geri dön
            img = Image.alpha_composite(img, overlay).convert("RGB")

        # Boyutu küçült (max 1280px genişlik — daha yüksek çözünürlük = daha isabetli tıklama)
        base_width = 1280
        w_percent = (base_width / float(img.size[0]))
        h_size = int((float(img.size[1]) * float(w_percent)))
        img = img.resize((base_width, h_size), Image.Resampling.LANCZOS)
        
        # JPEG olarak kaydet
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=90)
        return img_byte_arr.getvalue()

def hover_mouse(x: int, y: int) -> str:
    """
    Belirtilen x ve y koordinatlarına fareyi sadece götürür (tıklamaz).
    Bu aracı, bir tıklama yapmadan önce butonun etkileşimli olup olmadığını (hover efekti) görmek için kullan.
    
    Args:
        x: 0 ile 1000 arasında normalize X koordinatı.
        y: 0 ile 1000 arasında normalize Y koordinatı.
    """
    try:
        pyag = _require_pyautogui()
        width, height = pyag.size()
        real_x = int(round(float(x) * width / 1000))
        real_y = int(round(float(y) * height / 1000))
        pyag.moveTo(x=real_x, y=real_y, duration=0.2)
        return f"Fare ({real_x}, {real_y}) koordinatlarına götürüldü (Normalize: {x}, {y}). Tıklama yapılmadı."
    except Exception as e:
        return f"Fareyi hareket ettirme başarısız: {e}"

def get_pixel_color(x: int, y: int) -> str:
    """
    Belirtilen x ve y koordinatlarındaki pikselin RGB renk değerini döndürür.
    
    Args:
        x: 0 ile 1000 arasında normalize X koordinatı.
        y: 0 ile 1000 arasında normalize Y koordinatı.
    """
    try:
        pyag = _require_pyautogui()
        width, height = pyag.size()
        real_x = int(round(float(x) * width / 1000))
        real_y = int(round(float(y) * height / 1000))
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            r, g, b = img.getpixel((real_x, real_y))
            return f"Koordinat ({real_x}, {real_y}) için RGB renk değeri: ({r}, {g}, {b})"
    except Exception as e:
        return f"Renk bilgisi alınamadı: {e}"

def click_mouse(x: int, y: int) -> str:
    """
    Belirtilen x ve y koordinatlarına fare ile tıklar.
    
    Args:
        x: 0 ile 1000 arasında normalize X koordinatı.
        y: 0 ile 1000 arasında normalize Y koordinatı.
    """
    try:
        pyag = _require_pyautogui()
        width, height = pyag.size()
        real_x = int(round(float(x) * width / 1000))
        real_y = int(round(float(y) * height / 1000))
        pyag.click(x=real_x, y=real_y)
        return f"Fare ({real_x}, {real_y}) koordinatlarına tıklandı (Normalize: {x}, {y})."
    except Exception as e:
        return f"Tıklama başarısız: {e}"

def type_text(text: str) -> str:
    """Klavyeden belirtilen metni yazar.
    
    Args:
        text: Yazılacak metin.
    """
    try:
        pyag = _require_pyautogui()
        pyag.write(text, interval=0.01)
        return f"Klavyeden '{text}' yazıldı."
    except Exception as e:
        return f"Yazma başarısız: {e}"

def press_key(key: str) -> str:
    """Belirtilen özel tuşa basar.
    
    Args:
        key: Basılacak tuş (örn: 'enter', 'esc', 'tab').
    """
    try:
        pyag = _require_pyautogui()
        pyag.press(key)
        return f"'{key}' tuşuna basıldı."
    except Exception as e:
        return f"Tuş basımı başarısız: {e}"

def scroll_up(amount: int = 500) -> str:
    """
    Ekranı/Sayfayı YUKARI doğru kaydırır.
    
    Args:
        amount: Kaydırma miktarı (varsayılan: 500).
    """
    try:
        pyag = _require_pyautogui()
        pyag.scroll(amount)
        return f"Sayfa {amount} birim yukarı kaydırıldı."
    except Exception as e:
        return f"Yukarı kaydırma başarısız: {e}"

def scroll_down(amount: int = 500) -> str:
    """
    Ekranı/Sayfayı AŞAĞI doğru kaydırır. Genellikle aşağı inmek için bu aracı kullan.
    
    Args:
        amount: Kaydırma miktarı (varsayılan: 500).
    """
    try:
        # pyautogui'da negatif değer aşağı kaydırır
        pyag = _require_pyautogui()
        pyag.scroll(-abs(amount))
        return f"Sayfa {amount} birim aşağı kaydırıldı."
    except Exception as e:
        return f"Aşağı kaydırma başarısız: {e}"

def double_click_mouse(x: int, y: int) -> str:
    """
    Belirtilen x ve y koordinatlarına fare ile çift tıklar.
    
    Args:
        x: 0 ile 1000 arasında normalize X koordinatı.
        y: 0 ile 1000 arasında normalize Y koordinatı.
    """
    try:
        pyag = _require_pyautogui()
        width, height = pyag.size()
        real_x = int(round(float(x) * width / 1000))
        real_y = int(round(float(y) * height / 1000))
        pyag.doubleClick(x=real_x, y=real_y)
        return f"Fare ({real_x}, {real_y}) koordinatlarına çift tıklandı (Normalize: {x}, {y})."
    except Exception as e:
        return f"Çift tıklama başarısız: {e}"

def right_click_mouse(x: int, y: int) -> str:
    """
    Belirtilen x ve y koordinatlarına fare ile sağ tıklar.
    
    Args:
        x: 0 ile 1000 arasında normalize X koordinatı.
        y: 0 ile 1000 arasında normalize Y koordinatı.
    """
    try:
        pyag = _require_pyautogui()
        width, height = pyag.size()
        real_x = int(round(float(x) * width / 1000))
        real_y = int(round(float(y) * height / 1000))
        pyag.rightClick(x=real_x, y=real_y)
        return f"Fare ({real_x}, {real_y}) koordinatlarına sağ tıklandı (Normalize: {x}, {y})."
    except Exception as e:
        return f"Sağ tıklama başarısız: {e}"

def look_closer(x: int, y: int, radius: int = 100) -> bytes:
    """
    Belirtilen koordinatın çevresini (radius) yüksek çözünürlükte kırparak yakından bakmanı sağlar.
    Çok küçük metinleri okumak veya ikonları net görmek için bu aracı kullan.
    
    Args:
        x: 0-1000 arası normalize X koordinatı.
        y: 0-1000 arası normalize Y koordinatı.
        radius: Kırpılacak alanın yarıçapı (varsayılan 100 birim).
    """
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        
        # Orijinal boyut
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        w, h = img.size
        
        # Gerçek piksel koordinatları
        real_x = int(round(float(x) * w / 1000))
        real_y = int(round(float(y) * h / 1000))
        
        # Kırpılacak alanı belirle (normalize birimleri piksele çevir)
        px_radius_w = int(round(float(radius) * w / 1000))
        px_radius_h = int(round(float(radius) * h / 1000))
        
        left = max(0, real_x - px_radius_w)
        top = max(0, real_y - px_radius_h)
        right = min(w, real_x + px_radius_w)
        bottom = min(h, real_y + px_radius_h)
        
        # Crop
        img_crop = img.crop((left, top, right, bottom))
        
        # Zoom Izgarası Ekle (Seçmeli - Kırpılan alana özel 10x10 küçük grid)
        draw = ImageDraw.Draw(img_crop)
        cw, ch = img_crop.size
        for i in range(0, 11):
            # Dikey
            ix = int(i * cw / 10)
            draw.line([(ix, 0), (ix, ch)], fill=(255, 0, 0, 100), width=1)
            # Yatay
            iy = int(i * ch / 10)
            draw.line([(0, iy), (cw, iy)], fill=(255, 0, 0, 100), width=1)
        
        # Yakınlaştırılmış görüntüyü JPEG olarak döndür
        img_byte_arr = io.BytesIO()
        img_crop.save(img_byte_arr, format='JPEG', quality=95)
        return img_byte_arr.getvalue()

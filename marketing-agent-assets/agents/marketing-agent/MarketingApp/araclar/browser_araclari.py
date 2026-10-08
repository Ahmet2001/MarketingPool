"""
Browser Araçları — Selenium WebDriver ile gelişmiş web sayfası etkileşimi.

Özellikler:
  - Undetected ChromeDriver (bot algılama bypass)
  - Akıllı DOM Özeti (viewport-tabanlı, filtrelenmiş)
  - Element-Based Akıllı Bekleme
  - Cookie / Oturum Yönetimi
  - Sekme (Tab) Yönetimi
  - Dosya Yükleme
  - VLM Hibrit Görsel Analiz
"""

import os
import json
import time
import random
from difflib import SequenceMatcher
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# ─── Dizinler ────────────────────────────────────────────────────────────────
from MarketingApp.paths import workspace_path

_COOKIES_DIR = workspace_path("cookies")

# ─── Global Driver Instance ─────────────────────────────────────────────────
_driver = None
_driver_headless = None
_preferred_headless = False


def _get_action_delay_scale() -> float:
    try:
        value = float(os.getenv("BROWSER_ACTION_DELAY_SCALE", "0.45"))
    except Exception:
        value = 0.45
    return min(2.0, max(0.1, value))


_ACTION_DELAY_SCALE = _get_action_delay_scale()


def _sleep_scaled(seconds: float, floor: float = 0.03):
    time.sleep(max(floor, seconds * _ACTION_DELAY_SCALE))


def _sleep_range(min_seconds: float, max_seconds: float, floor: float = 0.03):
    time.sleep(max(floor, random.uniform(min_seconds, max_seconds) * _ACTION_DELAY_SCALE))


def _get_driver():
    """Mevcut driver'ı döndürür veya hata verir."""
    global _driver
    if _driver is None:
        raise RuntimeError("Tarayıcı henüz başlatılmadı. Önce browser_baslat() çağır.")
    return _driver


def get_browser_runtime_state() -> dict:
    """Terminal ve workflow katmani icin tarayici gorunurluk durumunu dondurur."""
    active_headless = bool(_driver_headless) if _driver is not None and _driver_headless is not None else None
    preferred_headless = bool(_preferred_headless)
    effective_headless = active_headless if active_headless is not None else preferred_headless
    return {
        "ready": _driver is not None,
        "active_headless": active_headless,
        "preferred_headless": preferred_headless,
        "effective_headless": effective_headless,
        "visibility_label": "Headless" if effective_headless else "Gorunur",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# A) TARAYICI BAŞLATMA — Undetected ChromeDriver Desteği
# ═══════════════════════════════════════════════════════════════════════════════

def browser_baslat(headless: bool = False) -> str:
    """
    Chrome tarayıcısını STEALTH modunda başlatır. Bot algılamayı bypass etmek için
    agresif anti-detection + kalıcı profil + medya izinleri + performans optimizasyonu kullanır.
    Bu araç diğer tüm browser araçlarından ÖNCE çağrılmalıdır.
    
    Args:
        headless: True ise arka planda çalışır (pencere açılmaz), False ise görünür modda çalışır (varsayılan False).
    """
    global _driver, _driver_headless, _preferred_headless
    try:
        _preferred_headless = bool(headless)
        if _driver is not None:
            current_mode = "headless" if _driver_headless else "görünür"
            return f"Tarayıcı zaten açık ({current_mode}). Yeni bir tane açmak için önce browser_kapat() çağır."

        # ── Kalıcı Chrome Profili (login bilgileri saklanır) ──
        profile_dir = workspace_path("chrome_profile")
        os.makedirs(profile_dir, exist_ok=True)

        # ── Anti-Detection + Performans Chrome Flags ──
        STEALTH_ARGS = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--window-size=1920,1080",
            "--lang=tr-TR,tr,en-US,en",
            "--start-maximized",
            "--ignore-certificate-errors",
            "--disable-popup-blocking",
            f"--user-data-dir={profile_dir}",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            # Performans (arka plan kısıtlamalarını kaldır)
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            # GPU / Render sorunlarını çöz
            "--disable-gpu",
            "--disable-gpu-compositing",
            "--disable-software-rasterizer",
        ]

        # ── Medya & Bildirim İzinleri (otomatik izin) ──
        PREFS = {
            "profile.default_content_setting_values.media_stream_mic": 1,     # Mikrofon: izin ver
            "profile.default_content_setting_values.media_stream_camera": 1,  # Kamera: izin ver
            "profile.default_content_setting_values.notifications": 2,        # Bildirimler: engelle
        }

        # Undetected ChromeDriver'ı dene, yoksa normal Selenium + webdriver-manager'a düş
        is_uc = False
        try:
            import undetected_chromedriver as uc
            chrome_options = uc.ChromeOptions()
            chrome_options.page_load_strategy = "eager"
            # UC kendi stealth yeteneklerine sahip olduğu için agresif flag'leri eklemiyoruz
            if headless:
                chrome_options.add_argument("--headless=new")
            
            _driver = uc.Chrome(
                options=chrome_options,
                user_data_dir=profile_dir
            )
            _driver_headless = bool(headless)
            driver_type = "Undetected ChromeDriver (stealth + kalıcı profil)"
            is_uc = True
        except Exception as uc_err:
            print(f"  ⚠️ Undetected ChromeDriver başarısız: {uc_err}. Normal Selenium'a geçiliyor...")
            from selenium import webdriver
            chrome_options = Options()
            chrome_options.page_load_strategy = "eager"
            for arg in STEALTH_ARGS:
                chrome_options.add_argument(arg)
            if headless:
                chrome_options.add_argument("--headless=new")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            chrome_options.add_experimental_option("prefs", PREFS)

            try:
                _driver = webdriver.Chrome(options=chrome_options)
                _driver_headless = bool(headless)
                driver_type = "Selenium ChromeDriver (selenium-manager + kalıcı profil)"
            except Exception as direct_err:
                print(f"  ⚠️ Doğrudan Chrome başlatma başarısız: {direct_err}. webdriver-manager deneniyor...")
                try:
                    from webdriver_manager.chrome import ChromeDriverManager
                    from selenium.webdriver.chrome.service import Service
                    service = Service(ChromeDriverManager().install())
                    _driver = webdriver.Chrome(service=service, options=chrome_options)
                    _driver_headless = bool(headless)
                    driver_type = "Selenium ChromeDriver (webdriver-manager + kalıcı profil)"
                except Exception as manager_err:
                    raise RuntimeError(
                        f"Doğrudan başlatma hatası: {direct_err} | webdriver-manager hatası: {manager_err}"
                    )

        # ── Post-Launch Stealth JavaScript Enjeksiyonu ──
        # UC kullanılıyorsa manuel enjeksiyon yapmıyoruz, çünkü kendisi yönetiyor.
        if not is_uc:
            _apply_stealth_scripts(_driver)

        _driver.implicitly_wait(5)
        mode_label = "headless" if headless else "görünür"
        return f"✅ Tarayıcı başlatıldı: {driver_type} | mod: {mode_label}"
    except Exception as e:
        _driver = None
        _driver_headless = None
        return f"❌ Tarayıcı başlatılamadı: {e}"


def browser_baglan(port: int = 9222) -> str:
    """
    Kullanıcının ZATEN AÇIK olan gerçek tarayıcısına (Chrome veya Edge) bağlanır.
    
    Bu yöntem %100 YAKALANMAZ çünkü:
    - Yeni bir tarayıcı açmaz, mevcut gerçek tarayıcıya bağlanır
    - Gerçek browsing geçmişi, cookie'ler ve eklentiler aynen korunur
    - Hiçbir otomasyon izi yoktur
    
    KULLANIM:
    1. Önce browser_chrome_baslat() ile tarayıcıyı debug modda başlat
    2. Sonra browser_baglan() ile bağlan
    
    Args:
        port: Remote Debugging portu (varsayılan 9222).
    """
    global _driver, _driver_headless, _preferred_headless
    try:
        if _driver is not None:
            return "Tarayıcı zaten bağlı. Yeni bağlantı için önce browser_kapat() çağır."
        
        from selenium import webdriver
        
        # Önce Edge ile dene (Windows'ta varsayılan tarayıcı)
        try:
            from selenium.webdriver.edge.options import Options as EdgeOptions
            from selenium.webdriver.edge.service import Service as EdgeService
            
            edge_options = EdgeOptions()
            edge_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
            
            # webdriver-manager ile EdgeDriver'ı otomatik indir ve kullan
            try:
                from webdriver_manager.microsoft import EdgeChromiumDriverManager
                edge_service = EdgeService(EdgeChromiumDriverManager().install())
                _driver = webdriver.Edge(service=edge_service, options=edge_options)
            except Exception:
                # webdriver-manager yoksa Selenium'un kendi otomatik yönetimine bırak
                _driver = webdriver.Edge(options=edge_options)
        except Exception as edge_err:
            # Edge başarısız olursa Chrome dene
            try:
                chrome_options = Options()
                chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
                
                # webdriver-manager ile ChromeDriver'ı otomatik indir ve kullan
                try:
                    from webdriver_manager.chrome import ChromeDriverManager
                    from selenium.webdriver.chrome.service import Service as ChromeService
                    chrome_service = ChromeService(ChromeDriverManager().install())
                    _driver = webdriver.Chrome(service=chrome_service, options=chrome_options)
                except Exception:
                    _driver = webdriver.Chrome(options=chrome_options)
            except Exception as chrome_err:
                raise Exception(f"Edge hatası: {edge_err} | Chrome hatası: {chrome_err}")
        
        _driver.implicitly_wait(5)
        _driver_headless = False
        _preferred_headless = False
        title = _driver.title
        url = _driver.current_url
        tab_count = len(_driver.window_handles)
        
        return (
            f"✅ Gerçek tarayıcıya bağlanıldı! (port {port})\n"
            f"   Aktif sayfa: '{title}'\n"
            f"   URL: {url}\n"
            f"   Açık sekme: {tab_count}\n"
            f"   ⚡ Bu tarayıcı %100 gerçek — hiçbir site bot olarak algılayamaz."
        )
    except Exception as e:
        _driver = None
        _driver_headless = None
        return (
            f"❌ Tarayıcıya bağlanılamadı (port {port}): {e}\n"
            f"   💡 Çözüm: Önce browser_chrome_baslat() çağır."
        )


def browser_chrome_baslat(port: int = 9222) -> str:
    """
    Chrome veya Edge tarayıcısını Remote Debugging modunda başlatır.
    Otomatik olarak sistemdeki tarayıcıyı bulur (Edge veya Chrome).
    Bu komuttan sonra browser_baglan() ile bağlanabilirsin.
    
    Args:
        port: Debug portu (varsayılan 9222).
    """
    try:
        import subprocess
        global _preferred_headless
        _preferred_headless = False
        
        # Tarayıcı yolları: Önce Edge, sonra Chrome (Edge daha yaygın Windows'ta)
        browser_candidates = [
            # Edge
            (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
            (os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
            (os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
            # Chrome
            (os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"), "Chrome"),
            (os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), "Chrome"),
            (os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"), "Chrome"),
        ]
        
        browser_path = None
        browser_name = None
        for path, name in browser_candidates:
            if os.path.exists(path):
                browser_path = path
                browser_name = name
                break
        
        if not browser_path:
            return (
                f"❌ Chrome veya Edge bulunamadı. Manuel başlat:\n"
                f"   msedge.exe --remote-debugging-port={port}\n"
                f"   veya: chrome.exe --remote-debugging-port={port}"
            )
        
        # Kalıcı profil dizini
        profile_dir = workspace_path("browser_debug_profile")
        os.makedirs(profile_dir, exist_ok=True)
        
        # Tarayıcıyı debug modda başlat
        subprocess.Popen([
            browser_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ])
        
        time.sleep(3)  # Tarayıcının açılmasını bekle
        
        return (
            f"✅ {browser_name} debug modda başlatıldı (port {port}).\n"
            f"   Yol: {browser_path}\n"
            f"   Şimdi browser_baglan() çağırarak bağlan."
        )
    except Exception as e:
        return f"❌ Tarayıcı başlatılamadı: {e}"


def _apply_stealth_scripts(driver):
    """Tarayıcı başlatıldıktan sonra anti-detection JavaScript'leri enjekte eder."""

    # 1. navigator.webdriver = false (en kritik kontrol)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """
    })

    # 2. Chrome runtime ve plugin'leri sahte olarak tanımla
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            // Chrome runtime mock
            window.chrome = {
                runtime: {
                    PlatformOs: {MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd'},
                    PlatformArch: {ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64'},
                    PlatformNaclArch: {ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64'},
                    RequestUpdateCheckStatus: {THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available'},
                    OnInstalledReason: {INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update'},
                    OnRestartRequiredReason: {APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic'},
                    connect: function() {},
                    sendMessage: function() {},
                },
            };

            // Plugins (gerçek Chrome'da en az 3 plugin var)
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'},
                    {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''},
                    {name: 'Native Client', filename: 'internal-nacl-plugin', description: ''},
                ],
            });

            // Languages (boş olmamalı)
            Object.defineProperty(navigator, 'languages', {
                get: () => ['tr-TR', 'tr', 'en-US', 'en'],
            });

            // Platform
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32',
            });

            // Hardware concurrency (gerçek CPU sayısı simüle)
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 8,
            });

            // DeviceMemory
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8,
            });

            // Permissions query override (notification permission kontrolünü bypass)
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({state: Notification.permission}) :
                    originalQuery(parameters)
            );

            // WebGL Vendor/Renderer (fingerprinting koruması)
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Intel Inc.';
                if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                return getParameter.apply(this, arguments);
            };
        """
    })

    # 3. CDP (Chrome DevTools Protocol) izlerini gizle
    driver.execute_cdp_cmd("Network.setUserAgentOverride", {
        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "platform": "Win32",
        "acceptLanguage": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
    })


# ═══════════════════════════════════════════════════════════════════════════════
# B) NAVİGASYON
# ═══════════════════════════════════════════════════════════════════════════════

def browser_git(url: str) -> str:
    """
    Tarayıcıyı belirtilen URL adresine götürür.
    
    Args:
        url: Gidilecek tam web adresi (örn: 'https://x.com')
    """
    try:
        driver = _get_driver()
        driver.get(url)
        _sleep_scaled(1.2)
        title = driver.title
        return f"✅ Sayfa açıldı: '{title}' ({url})"
    except Exception as e:
        return f"❌ Sayfaya gidilemedi: {e}"


def browser_geri() -> str:
    """Tarayıcıda bir önceki sayfaya döner (Geri butonu)."""
    try:
        driver = _get_driver()
        driver.back()
        _sleep_scaled(0.8)
        return f"✅ Önceki sayfaya dönüldü: {driver.title}"
    except Exception as e:
        return f"❌ Geri gidemedi: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# C) AKILLI DOM ÖZETİ (Viewport-filtrelenmiş, konum bilgili)
# ═══════════════════════════════════════════════════════════════════════════════

def _dom_ozeti_uret(max_eleman: int = 100, sayfa_metni: bool = True) -> str:
    """DOM bilgisini tam veya hafif ozet modunda uretir."""
    js_script = """
    const elements = document.querySelectorAll(
        "a, button, input, textarea, select, [role='button'], [role='link'], " +
        "[role='menuitem'], [role='tab'], [onclick], [tabindex]"
    );

    let result = [];
    let counter = 0;
    const vHeight = window.innerHeight;

    for (let el of elements) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

        // Viewport filtreleme: çok yukarıda veya çok aşağıda olanları dahil etme (-1000px to +1500px)
        if (rect.top < -1000 || rect.top > vHeight + 1500) continue;

        const marId = String(counter);
        el.setAttribute('data-mar-id', marId);
        
        let pos = "ORTA";
        if (rect.top < vHeight * 0.33) pos = "ÜST";
        else if (rect.top > vHeight * 0.66) pos = "ALT";
        
        const tag = el.tagName.toLowerCase();
        let text = "";
        if (el.innerText) {
            text = el.innerText.trim().substring(0, 50).replace(/[\\n\\r]+/g, ' ');
        }
        const ariaLabel = el.getAttribute('aria-label') || "";
        const dataTestId = el.getAttribute('data-testid') || "";
        const placeholder = el.getAttribute('placeholder') || "";
        const href = el.getAttribute('href') || "";
        const type = el.getAttribute('type') || "";
        const name = el.getAttribute('name') || "";
        const title = el.getAttribute('title') || "";
        let value = el.value || "";
        if (typeof value !== 'string') value = "";

        result.push({
            id: marId,
            pos: pos,
            tag: tag,
            text: text,
            ariaLabel: ariaLabel,
            dataTestId: dataTestId,
            placeholder: placeholder,
            value: value.substring(0, 30),
            name: name,
            href: href.substring(0, 60),
            type: type,
            title: title.substring(0, 30),
            top: rect.top
        });
        counter++;
    }
    result.sort((a, b) => a.top - b.top);
    return result;
    """
    try:
        driver = _get_driver()
        results = driver.execute_script(js_script)
        
        lines = []
        lines.append(f"📄 Sayfa: {driver.title}")
        lines.append(f"🔗 URL: {driver.current_url}")
        lines.append("─" * 50)
        
        if not results:
            lines.append("  (Sayfada görünür etkileşimli eleman bulunamadı)")
        else:
            lines.append(f"ETKİLEŞİMLİ ELEMANLAR ({len(results)} adet incelendi):")
            for item in results[:max(1, max_eleman)]:
                desc_parts = []
                if item.get("text"): desc_parts.append(f'"{item["text"]}"')
                if item.get("dataTestId"): desc_parts.append(f'testid="{item["dataTestId"]}"')
                if item.get("ariaLabel") and item.get("ariaLabel") != item.get("text"): 
                    desc_parts.append(f'aria="{item["ariaLabel"]}"')
                if item.get("placeholder"): desc_parts.append(f'placeholder="{item["placeholder"]}"')
                if item.get("title") and item.get("title") != item.get("text"): 
                    desc_parts.append(f'title="{item["title"]}"')
                if item.get("value"): desc_parts.append(f'value="{item["value"]}"')
                if item.get("name"): desc_parts.append(f'name="{item["name"]}"')
                if item.get("href"): 
                    h = item["href"]
                    short_href = h + "..." if len(h) == 60 else h
                    desc_parts.append(f'href="{short_href}"')
                if item.get("type"): desc_parts.append(f'type="{item["type"]}"')

                desc = " | ".join(desc_parts) if desc_parts else "(boş/ikon)"
                lines.append(f"  [{item['id']}] [{item['pos']}] <{item['tag']}> {desc}")

        if sayfa_metni:
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                if body_text:
                    summary = body_text[:600].replace("\n", " | ")
                    lines.append("─" * 50)
                    lines.append(f"SAYFA METNİ (özet): {summary}")
            except Exception:
                pass

        return "\n".join(lines)
    except Exception as e:
        return f"❌ DOM okunamadı: {e}"


def browser_dom_oku() -> str:
    """
    Sayfadaki etkileşimli elemanları Javascript ile analiz edip numaralandırır.
    Elemanlara 'data-mar-id' atar ve LLM'e okunabilir liste sunar.
    Özellikle X (Twitter) gibi karmaşık DOM yapılarında isabetli tıklama sağlar.
    """
    return _dom_ozeti_uret(max_eleman=80, sayfa_metni=True)


def browser_hizli_durum_oku() -> str:
    """
    Sayfanın hafif ve hızlı bir durum özetini verir.
    Rutin doğrulama ve ara kontroller için bunu, detay gerektiğinde browser_dom_oku'yu kullan.
    """
    return _dom_ozeti_uret(max_eleman=28, sayfa_metni=False)


# ═══════════════════════════════════════════════════════════════════════════════
# D) TIKLAMA ve METİN GİRİŞİ
# ═══════════════════════════════════════════════════════════════════════════════

_INTERACTIVE_SELECTOR = (
    "a, button, input, textarea, select, label, "
    "[role='button'], [role='link'], [role='menuitem'], [role='tab'], "
    "[role='textbox'], [onclick], [tabindex], [contenteditable]"
)

_TEXT_INPUT_SELECTOR = (
    "input:not([type='hidden']):not([type='file']):not([type='checkbox']):not([type='radio']), "
    "textarea, [role='textbox'], [contenteditable]"
)

_TEXT_NORMALIZE_MAP = str.maketrans({
    "I": "i",
    "İ": "i",
    "ı": "i",
    "Ş": "s",
    "ş": "s",
    "Ğ": "g",
    "ğ": "g",
    "Ü": "u",
    "ü": "u",
    "Ö": "o",
    "ö": "o",
    "Ç": "c",
    "ç": "c",
})


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip().translate(_TEXT_NORMALIZE_MAP).casefold()


def _truncate_text(value: str, limit: int = 60) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _get_associated_label_text(driver, element) -> str:
    try:
        label_text = driver.execute_script("""
            const el = arguments[0];
            if (!el) return "";

            const values = [];
            const pushText = (value) => {
                const text = String(value || "").replace(/\\s+/g, " ").trim();
                if (text && !values.includes(text)) values.push(text);
            };

            const labelledBy = (el.getAttribute("aria-labelledby") || "").trim();
            if (labelledBy) {
                labelledBy.split(/\\s+/).forEach((id) => {
                    const ref = document.getElementById(id);
                    if (ref) pushText(ref.innerText || ref.textContent || "");
                });
            }

            if (el.labels && el.labels.length) {
                Array.from(el.labels).forEach((label) => pushText(label.innerText || label.textContent || ""));
            }

            const parentLabel = el.closest("label");
            if (parentLabel) {
                pushText(parentLabel.innerText || parentLabel.textContent || "");
            }

            if (!values.length) {
                const id = el.getAttribute("id");
                if (id) {
                    const explicitLabel = Array.from(document.querySelectorAll("label[for]"))
                        .find((label) => label.htmlFor === id);
                    if (explicitLabel) {
                        pushText(explicitLabel.innerText || explicitLabel.textContent || "");
                    }
                }
            }

            return values.join(" | ").slice(0, 160);
        """, element)
        return " ".join(str(label_text or "").split()).strip()
    except Exception:
        return ""


def _ensure_mar_id(driver, element) -> str:
    try:
        existing = (element.get_attribute("data-mar-id") or "").strip()
        if existing:
            return existing

        mar_id = driver.execute_script("""
            const el = arguments[0];
            if (!el) return "";
            const current = (el.getAttribute("data-mar-id") || "").trim();
            if (current) return current;

            const existingIds = Array.from(document.querySelectorAll("[data-mar-id]"))
                .map((node) => parseInt(node.getAttribute("data-mar-id"), 10))
                .filter((value) => Number.isFinite(value));
            const nextId = existingIds.length ? Math.max(...existingIds) + 1 : 0;
            el.setAttribute("data-mar-id", String(nextId));
            return String(nextId);
        """, element)
        return str(mar_id or "").strip()
    except Exception:
        return ""


def _collect_element_fields(driver, element) -> dict:
    try:
        tag = element.tag_name or ""
        role = (element.get_attribute("role") or "").strip()
        text = (element.text or "").strip()
        if not text:
            try:
                text = (driver.execute_script(
                    "return ((arguments[0].innerText || arguments[0].textContent || '').trim()).slice(0, 120);",
                    element,
                ) or "").strip()
            except Exception:
                text = ""

        fields = {
            "tag": tag,
            "text": text,
            "aria": (element.get_attribute("aria-label") or "").strip(),
            "placeholder": (element.get_attribute("placeholder") or "").strip(),
            "testid": (element.get_attribute("data-testid") or "").strip(),
            "title": (element.get_attribute("title") or "").strip(),
            "value": (element.get_attribute("value") or "").strip(),
            "name": (element.get_attribute("name") or "").strip(),
            "role": role,
            "type": (element.get_attribute("type") or "").strip(),
            "id_attr": (element.get_attribute("id") or "").strip(),
            "class": (element.get_attribute("class") or "").strip(),
            "href": (element.get_attribute("href") or "").strip(),
            "contenteditable": (element.get_attribute("contenteditable") or "").strip(),
            "disabled": not element.is_enabled(),
            "label": "",
            "mar_id": (element.get_attribute("data-mar-id") or "").strip(),
        }
        if tag in ("input", "textarea", "select") or role == "textbox" or fields["contenteditable"] == "true":
            fields["label"] = _get_associated_label_text(driver, element)
        return fields
    except Exception:
        return {
            "tag": "",
            "text": "",
            "aria": "",
            "placeholder": "",
            "testid": "",
            "title": "",
            "value": "",
            "name": "",
            "role": "",
            "type": "",
            "id_attr": "",
            "class": "",
            "href": "",
            "contenteditable": "",
            "disabled": False,
            "label": "",
            "mar_id": "",
        }


def _describe_element(fields: dict) -> str:
    parts = [f"<{fields.get('tag') or 'element'}>"]
    if fields.get("text"):
        parts.append(f'text="{_truncate_text(fields["text"], 50)}"')
    if fields.get("aria"):
        parts.append(f'aria="{_truncate_text(fields["aria"], 40)}"')
    if fields.get("placeholder"):
        parts.append(f'placeholder="{_truncate_text(fields["placeholder"], 40)}"')
    if fields.get("label"):
        parts.append(f'label="{_truncate_text(fields["label"], 40)}"')
    if fields.get("testid"):
        parts.append(f'testid="{_truncate_text(fields["testid"], 30)}"')
    if fields.get("id_attr"):
        parts.append(f'id="{_truncate_text(fields["id_attr"], 24)}"')
    if fields.get("role"):
        parts.append(f'role="{fields["role"]}"')
    if fields.get("type"):
        parts.append(f'type="{fields["type"]}"')
    if fields.get("mar_id"):
        parts.append(f'mar_id="{fields["mar_id"]}"')
    if len(parts) == 1 and fields.get("value"):
        parts.append(f'value="{_truncate_text(fields["value"], 40)}"')
    if fields.get("disabled"):
        parts.append("disabled")
    return " ".join(parts)


def _score_field_match(query_norm: str, candidate_value: str, exact_score: int, contains_score: int) -> tuple[int, str]:
    candidate_norm = _normalize_text(candidate_value)
    if not query_norm or not candidate_norm:
        return 0, ""
    if candidate_norm == query_norm:
        return exact_score, "exact"
    if candidate_norm.startswith(query_norm) or query_norm.startswith(candidate_norm):
        return exact_score - 10, "prefix"
    if query_norm in candidate_norm:
        return contains_score, "contains"

    query_tokens = query_norm.split()
    candidate_tokens = candidate_norm.split()
    overlap = 0
    for token in query_tokens:
        if any(token == cand or token in cand or cand in token for cand in candidate_tokens):
            overlap += 1

    if query_tokens and overlap == len(query_tokens):
        return max(1, contains_score - 10), f"all_tokens:{overlap}"
    if query_tokens and overlap >= max(1, len(query_tokens) - 1):
        return max(1, contains_score - 20), f"token_overlap:{overlap}"

    similarity = SequenceMatcher(None, query_norm, candidate_norm).ratio()
    if similarity >= 0.92:
        return max(contains_score, exact_score - 18), f"fuzzy:{similarity:.2f}"
    if similarity >= 0.84:
        return max(1, contains_score - 14), f"fuzzy:{similarity:.2f}"
    return 0, ""


def _field_weights(field_name: str) -> tuple[int, int]:
    weights = {
        "text": (150, 120),
        "aria": (135, 108),
        "label": (140, 112),
        "placeholder": (130, 104),
        "testid": (120, 92),
        "title": (105, 78),
        "value": (95, 70),
        "name": (85, 64),
        "role": (70, 52),
        "id_attr": (100, 76),
        "href": (70, 48),
        "class": (55, 40),
    }
    return weights.get(field_name, (80, 60))


def _score_to_confidence(score: int) -> str:
    if score >= 240:
        return "cok_yuksek"
    if score >= 180:
        return "yuksek"
    if score >= 120:
        return "orta"
    return "dusuk"


_DOM_QUERY_STOPWORDS = {
    "ac", "ama", "ancak", "artik", "asagi", "asagidaki", "az", "bana", "bazı", "bazi",
    "ben", "bir", "biraz", "biri", "birini", "biz", "bu", "burada", "buradaki", "buraya",
    "buyuk", "cok", "daha", "de", "da", "diye", "dogru", "dolayi", "en", "gibi", "gore",
    "göre", "hangi", "hemen", "hem", "icin", "için", "ile", "ise", "iste", "istegi",
    "kadar", "karar", "kendi", "kez", "ki", "mi", "mu", "mü", "na", "ne", "neden", "nerede",
    "nasil", "nasilsa", "olan", "olarak", "oldugu", "olduğu", "once", "önce", "orada",
    "sadece", "sanki", "sekilde", "seklinde", "simdi", "şimdi", "sonra", "su", "şu",
    "tam", "tum", "tüm", "uzerinde", "üzerinde", "var", "ve", "veya", "ya", "yani",
}


def _build_query_candidates(query: str) -> list[tuple[str, str]]:
    normalized = _normalize_text(query)
    if not normalized:
        return []

    candidates = []
    seen = set()

    def add_candidate(kind: str, value: str):
        text = " ".join(str(value or "").split()).strip()
        if not text or text in seen:
            return
        seen.add(text)
        candidates.append((kind, text))

    add_candidate("full", normalized)

    tokens = []
    for raw_token in normalized.split():
        token = raw_token.strip(".,:;!?()[]{}<>\"'`/")
        if len(token) < 2 or token in _DOM_QUERY_STOPWORDS:
            continue
        tokens.append(token)

    for idx in range(max(0, len(tokens) - 1)):
        add_candidate("phrase", f"{tokens[idx]} {tokens[idx + 1]}")
        if len(candidates) >= 7:
            break

    for token in tokens[:14]:
        add_candidate("token", token)

    return candidates


def _score_chunk_field(query_candidates: list[tuple[str, str]], candidate_value: str, field_name: str) -> tuple[int, str]:
    exact_score, contains_score = _field_weights(field_name)
    kind_multiplier = {
        "full": 1.0,
        "phrase": 0.9,
        "token": 0.68,
    }

    best_score = 0
    best_reason = ""
    for kind, query in query_candidates:
        raw_score, reason = _score_field_match(query, candidate_value, exact_score, contains_score)
        adjusted_score = int(raw_score * kind_multiplier.get(kind, 1.0))
        if adjusted_score > best_score:
            best_score = adjusted_score
            best_reason = f"{field_name}:{kind}:{reason}"
    return best_score, best_reason


def _collect_sectional_dom_snapshot(driver, max_elements: int = 140) -> dict:
    js_script = """
    const MAX_ELEMENTS = arguments[0];
    const selector =
        "a, button, input, textarea, select, label, " +
        "[role='button'], [role='link'], [role='menuitem'], [role='tab'], " +
        "[role='textbox'], [onclick], [tabindex], [contenteditable]";

    const viewportHeight = window.innerHeight || 900;
    const scrollY = window.scrollY || 0;
    const maxAbove = 1400;
    const maxBelow = 3200;

    const cleanText = (value, limit = 120) => {
        const text = String(value || "").replace(/\\s+/g, " ").trim();
        return text.length <= limit ? text : text.slice(0, limit - 3) + "...";
    };

    const elementText = (el, limit = 120) => cleanText(el.innerText || el.textContent || "", limit);

    const collectLabelText = (el) => {
        const values = [];
        const pushText = (value) => {
            const text = cleanText(value, 100);
            if (text && !values.includes(text)) values.push(text);
        };

        const labelledBy = (el.getAttribute("aria-labelledby") || "").trim();
        if (labelledBy) {
            labelledBy.split(/\\s+/).forEach((id) => {
                const ref = document.getElementById(id);
                if (ref) pushText(ref.innerText || ref.textContent || "");
            });
        }

        if (el.labels && el.labels.length) {
            Array.from(el.labels).forEach((label) => pushText(label.innerText || label.textContent || ""));
        }

        const parentLabel = el.closest("label");
        if (parentLabel) {
            pushText(parentLabel.innerText || parentLabel.textContent || "");
        }

        if (!values.length) {
            const fieldId = el.getAttribute("id");
            if (fieldId) {
                const explicitLabel = Array.from(document.querySelectorAll("label[for]"))
                    .find((label) => label.htmlFor === fieldId);
                if (explicitLabel) pushText(explicitLabel.innerText || explicitLabel.textContent || "");
            }
        }

        return values.join(" | ").slice(0, 120);
    };

    const detectSectionMeta = (el, globalTop) => {
        const bandIndex = Math.max(0, Math.floor(globalTop / 420));
        const container = el.closest("dialog, [role='dialog'], form, nav, header, footer, main, aside, section, article");

        if (!container) {
            return {
                sectionType: "band",
                sectionKey: `band:${bandIndex}`,
                sectionLabel: `Band ${bandIndex}`,
                bandIndex,
            };
        }

        let sectionType = "section";
        if (container.matches("dialog, [role='dialog']")) sectionType = "dialog";
        else if (container.matches("form")) sectionType = "form";
        else if (container.matches("nav")) sectionType = "nav";
        else if (container.matches("header")) sectionType = "header";
        else if (container.matches("footer")) sectionType = "footer";
        else if (container.matches("main")) sectionType = "main";
        else if (container.matches("aside")) sectionType = "aside";
        else if (container.matches("article")) sectionType = "article";

        let sectionLabel =
            cleanText(container.getAttribute("aria-label") || "", 80) ||
            cleanText(container.getAttribute("data-testid") || "", 80) ||
            cleanText(container.id || "", 80);

        if (!sectionLabel) {
            const heading = container.querySelector("h1, h2, h3, [role='heading'], legend, label");
            if (heading) sectionLabel = elementText(heading, 80);
        }

        if (!sectionLabel) {
            sectionLabel = `${sectionType} ${bandIndex}`;
        }

        const rawKey =
            cleanText(container.getAttribute("data-testid") || "", 40) ||
            cleanText(container.getAttribute("aria-label") || "", 40) ||
            cleanText(container.id || "", 40) ||
            `${container.tagName.toLowerCase()}-${bandIndex}`;

        return {
            sectionType,
            sectionKey: `${sectionType}:${rawKey}:${bandIndex}`,
            sectionLabel,
            bandIndex,
        };
    };

    const results = [];
    let fallbackId = 0;

    for (const el of Array.from(document.querySelectorAll(selector))) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;

        const style = window.getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") continue;
        if (rect.top < -maxAbove || rect.top > viewportHeight + maxBelow) continue;

        const globalTop = Math.round(rect.top + scrollY);
        let marId = String(el.getAttribute("data-mar-id") || "").trim();
        if (!marId) {
            marId = String(fallbackId++);
            el.setAttribute("data-mar-id", marId);
        }

        const meta = detectSectionMeta(el, globalTop);
        const tag = (el.tagName || "").toLowerCase();
        const role = cleanText(el.getAttribute("role") || "", 40);
        const isInputLike = ["input", "textarea", "select"].includes(tag) || role === "textbox" || el.getAttribute("contenteditable") === "true";

        let pos = "ORTA";
        if (rect.top < viewportHeight * 0.33) pos = "UST";
        else if (rect.top > viewportHeight * 0.66) pos = "ALT";

        results.push({
            mar_id: marId,
            tag,
            text: elementText(el, 90),
            aria: cleanText(el.getAttribute("aria-label") || "", 80),
            label: isInputLike ? collectLabelText(el) : "",
            placeholder: cleanText(el.getAttribute("placeholder") || "", 80),
            testid: cleanText(el.getAttribute("data-testid") || "", 60),
            title: cleanText(el.getAttribute("title") || "", 60),
            value: cleanText(el.value || "", 50),
            name: cleanText(el.getAttribute("name") || "", 60),
            role,
            type: cleanText(el.getAttribute("type") || "", 32),
            id_attr: cleanText(el.getAttribute("id") || "", 48),
            href: cleanText(el.getAttribute("href") || "", 80),
            class: cleanText(el.getAttribute("class") || "", 80),
            disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true",
            pos,
            top: globalTop,
            section_key: meta.sectionKey,
            section_type: meta.sectionType,
            section_label: meta.sectionLabel,
            band_index: meta.bandIndex,
        });
    }

    results.sort((a, b) => a.top - b.top);
    return {
        title: document.title || "",
        url: window.location.href,
        viewport_top: Math.round(scrollY),
        viewport_height: Math.round(viewportHeight),
        elements: results.slice(0, Math.max(1, MAX_ELEMENTS)),
    };
    """
    try:
        snapshot = driver.execute_script(js_script, max(20, max_elements))
        if isinstance(snapshot, dict):
            return snapshot
        return {"title": driver.title, "url": driver.current_url, "viewport_top": 0, "viewport_height": 0, "elements": []}
    except Exception:
        return {"title": driver.title, "url": driver.current_url, "viewport_top": 0, "viewport_height": 0, "elements": []}


def _build_dom_chunks_from_snapshot(snapshot: dict, max_chunk_items: int = 7) -> list[dict]:
    elements = list(snapshot.get("elements") or [])
    if not elements:
        return []

    grouped: dict[str, list[dict]] = {}
    for item in elements:
        section_key = item.get("section_key") or f"band:{item.get('band_index', 0)}"
        grouped.setdefault(section_key, []).append(item)

    chunks = []
    for section_key, items in grouped.items():
        first_item = items[0]
        total_parts = max(1, (len(items) + max_chunk_items - 1) // max_chunk_items)
        for offset in range(0, len(items), max_chunk_items):
            subset = items[offset: offset + max_chunk_items]
            chunk_index = len(chunks)
            part = (offset // max_chunk_items) + 1
            input_count = 0
            action_count = 0
            for entry in subset:
                tag = entry.get("tag") or ""
                role = entry.get("role") or ""
                if tag in ("input", "textarea", "select") or role == "textbox":
                    input_count += 1
                if tag in ("button", "a", "label") or role in ("button", "link", "tab", "menuitem"):
                    action_count += 1

            chunks.append({
                "index": chunk_index,
                "section_key": section_key,
                "section_type": first_item.get("section_type") or "band",
                "section_label": first_item.get("section_label") or f"Bolum {chunk_index + 1}",
                "top": subset[0].get("top", 0),
                "bottom": subset[-1].get("top", 0),
                "items": subset,
                "part": part,
                "part_count": total_parts,
                "input_count": input_count,
                "action_count": action_count,
            })

    return chunks


def _score_dom_chunk(gorev: str, chunk: dict) -> tuple[int, list[str]]:
    query_candidates = _build_query_candidates(gorev)
    if not query_candidates:
        return 0, []

    gorev_norm = _normalize_text(gorev)
    score = 0
    reasons: list[str] = []

    chunk_label_score, chunk_label_reason = _score_chunk_field(query_candidates, chunk.get("section_label", ""), "label")
    if chunk_label_score > 0:
        score += chunk_label_score
        reasons.append(chunk_label_reason)

    chunk_type_score, chunk_type_reason = _score_chunk_field(query_candidates, chunk.get("section_type", ""), "role")
    if chunk_type_score > 0:
        score += chunk_type_score // 2
        reasons.append(chunk_type_reason)

    task_is_write = any(marker in gorev_norm for marker in ("yaz", "gir", "doldur", "alan", "input", "textbox", "e-posta", "eposta", "sifre", "password"))
    task_is_click = any(marker in gorev_norm for marker in ("tikla", "bas", "ac", "gonder", "submit", "devam", "buton", "button", "sec", "seç"))
    task_is_comment = any(marker in gorev_norm for marker in ("yorum", "comment", "reply", "yanit", "yazit", "tweet", "post"))

    element_scores = []
    for item in chunk.get("items", []):
        item_score = 0
        item_reasons = []
        for field_name in ("text", "aria", "label", "placeholder", "testid", "title", "name", "id_attr", "value", "href"):
            field_score, field_reason = _score_chunk_field(query_candidates, item.get(field_name, ""), field_name)
            if field_score > 0:
                item_score += field_score
                item_reasons.append(field_reason)

        combined_text = " ".join(
            str(item.get(field) or "")
            for field in ("text", "aria", "label", "placeholder", "testid", "title")
        )
        combined_norm = _normalize_text(combined_text)

        if task_is_write and (item.get("tag") in ("input", "textarea", "select") or item.get("role") == "textbox"):
            item_score += 26
        if task_is_click and (item.get("tag") in ("button", "a", "label") or item.get("role") in ("button", "link", "tab", "menuitem")):
            item_score += 20
        if task_is_comment and any(keyword in combined_norm for keyword in ("yorum", "comment", "reply", "yanit", "post", "tweet")):
            item_score += 18
        if item.get("disabled"):
            item_score -= 35

        if item_score > 0:
            element_scores.append((item_score, item, item_reasons))

    element_scores.sort(key=lambda entry: entry[0], reverse=True)
    for item_score, item, item_reasons in element_scores[:3]:
        score += item_score
        descriptor = _describe_element(item)
        reason_summary = ", ".join(item_reasons[:3]) if item_reasons else "alan-eslesmesi"
        reasons.append(f"{descriptor} [{reason_summary}]")

    if task_is_write and chunk.get("section_type") == "form":
        score += 24
    if task_is_write:
        score += min(24, chunk.get("input_count", 0) * 6)
    if task_is_click:
        score += min(20, chunk.get("action_count", 0) * 4)
    if task_is_comment and any("comment" in _normalize_text(str(item.get("section_label", ""))) for item in chunk.get("items", [])):
        score += 12

    return score, reasons[:5]


def _format_dom_chunk(chunk: dict, relation: str = "ASIL") -> str:
    score = chunk.get("_score", 0)
    confidence = chunk.get("_confidence", _score_to_confidence(score))
    label = chunk.get("section_label") or f"Bolum {chunk.get('index', 0) + 1}"
    section_type = chunk.get("section_type") or "band"
    part = chunk.get("part", 1)
    part_count = chunk.get("part_count", 1)
    part_suffix = f" parca {part}/{part_count}" if part_count > 1 else ""

    lines = [
        f"[{relation}] Bolum {chunk.get('index', 0) + 1}{part_suffix} | skor={score} | guven={confidence}",
        f"Tur: {section_type} | Etiket: {label}",
        f"Konum: top={chunk.get('top', 0)} bottom={chunk.get('bottom', 0)} | input={chunk.get('input_count', 0)} | aksiyon={chunk.get('action_count', 0)}",
    ]

    reasons = chunk.get("_reasons") or []
    if reasons:
        lines.append("Neden:")
        for reason in reasons[:3]:
            lines.append(f"  - {reason}")

    lines.append("Elemanlar:")
    items = chunk.get("items", [])
    for item in items[:6]:
        lines.append(f"  [{item.get('mar_id', '?')}] {_describe_element(item)}")
    if len(items) > 6:
        lines.append(f"  ... (+{len(items) - 6} eleman)")

    return "\n".join(lines)


def browser_ilgili_bolumleri_getir(gorev: str, top_k: int = 2, komsu_sayisi: int = 1) -> str:
    """
    Mevcut sayfayi mantikli DOM bolumlerine ayirir ve goreve en ilgili bolumleri secip ozetler.
    Chunk secimini modele birakmak yerine once kod tarafinda deterministik siralama yapar.

    Args:
        gorev: Hangi bolumlerin ilgili oldugunu belirlemek icin gorev/aciklama metni.
        top_k: En ilgili kac ana bolum secilecegi.
        komsu_sayisi: Her ana bolum icin soldan/sagdan kac komsu bolumun baglam olarak eklenecegi.
    """
    try:
        driver = _get_driver()
        snapshot = _collect_sectional_dom_snapshot(driver, max_elements=150)
        chunks = _build_dom_chunks_from_snapshot(snapshot, max_chunk_items=7)
        if not chunks:
            return "❌ Sayfada secilebilir DOM bolumu bulunamadi."

        score_map: dict[int, dict] = {}
        for chunk in chunks:
            score, reasons = _score_dom_chunk(gorev, chunk)
            chunk["_score"] = score
            chunk["_reasons"] = reasons
            chunk["_confidence"] = _score_to_confidence(score)
            score_map[chunk["index"]] = chunk

        ranked = sorted(chunks, key=lambda item: item.get("_score", 0), reverse=True)
        top_k = max(1, min(int(top_k), 5))
        komsu_sayisi = max(0, min(int(komsu_sayisi), 2))

        primary_chunks = ranked[:top_k]
        selected_indices = set()
        selected_chunks = []
        primary_index_map = {chunk["index"]: rank + 1 for rank, chunk in enumerate(primary_chunks)}

        for primary_chunk in primary_chunks:
            idx = primary_chunk["index"]
            start = max(0, idx - komsu_sayisi)
            end = min(len(chunks), idx + komsu_sayisi + 1)
            for candidate_idx in range(start, end):
                if candidate_idx in selected_indices:
                    continue
                selected_indices.add(candidate_idx)
                selected_chunks.append(score_map[candidate_idx])

        selected_chunks.sort(key=lambda item: item["index"])
        best_score = primary_chunks[0].get("_score", 0) if primary_chunks else 0

        lines = [
            f"🎯 Goreve gore ilgili DOM bolumleri secildi",
            f"Gorev: {gorev}",
            f"Sayfa: {snapshot.get('title', '')}",
            f"URL: {snapshot.get('url', '')}",
            f"Toplam bolum: {len(chunks)} | Secilen bolum: {len(selected_chunks)}",
        ]

        if best_score < 90:
            lines.append("⚠️ Eslesme guveni dusuk. Gerekirse `browser_dom_oku()` ile daha genis inceleme yap.")

        for chunk in selected_chunks:
            relation = "ASIL" if chunk["index"] in primary_index_map else "KOMSU"
            if relation == "ASIL":
                relation = f"ASIL#{primary_index_map[chunk['index']]}"
            lines.append("")
            lines.append(_format_dom_chunk(chunk, relation=relation))

        return "\n".join(lines)
    except Exception as e:
        return f"❌ Ilgili bolum secimi basarisiz: {e}"


def _find_matching_elements(
    driver,
    sorgu: str,
    css_selector: str,
    alanlar: list[str] | None = None,
    limit: int = 8,
    include_disabled: bool = True,
) -> list[tuple[int, object, dict]]:
    query_norm = _normalize_text(sorgu)
    if not query_norm:
        return []

    allowed_fields = [field.strip().lower() for field in (alanlar or ["text", "aria", "testid"]) if field.strip()]
    candidates = []

    for element in driver.find_elements(By.CSS_SELECTOR, css_selector):
        if not _is_visible(element):
            continue

        fields = _collect_element_fields(driver, element)
        if fields.get("disabled") and not include_disabled:
            continue

        score = 0
        match_notes = []
        for field_name in allowed_fields:
            exact_score, contains_score = _field_weights(field_name)
            field_score, reason = _score_field_match(query_norm, fields.get(field_name, ""), exact_score, contains_score)
            score += field_score
            if field_score > 0:
                match_notes.append(f"{field_name}:{reason}")

        if score <= 0:
            continue

        if fields.get("tag") in ("button", "a"):
            score += 5
        if fields.get("role") in ("button", "link", "menuitem", "tab"):
            score += 5
        if fields.get("tag") in ("input", "textarea", "select") or fields.get("contenteditable") == "true":
            score += 3
        if fields.get("disabled"):
            score -= 35

        fields["_match_notes"] = match_notes[:4]
        fields["_confidence"] = _score_to_confidence(score)

        candidates.append((score, element, fields))

    candidates.sort(key=lambda item: item[0], reverse=True)
    top_candidates = candidates[:limit]
    for _score, element, fields in top_candidates:
        fields["mar_id"] = _ensure_mar_id(driver, element)
    return top_candidates


def _focus_and_clear_element(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    _sleep_range(0.25, 0.8)
    try:
        ActionChains(driver).move_to_element(element).click().perform()
    except Exception:
        try:
            element.click()
        except Exception:
            driver.execute_script("arguments[0].focus();", element)
    _sleep_scaled(0.15)
    try:
        element.send_keys(Keys.CONTROL + "a")
        element.send_keys(Keys.DELETE)
    except Exception:
        driver.execute_script("""
            const el = arguments[0];
            const editable = el.getAttribute("contenteditable");
            if (editable && editable !== "false") {
                el.innerHTML = "";
                el.textContent = "";
            } else {
                el.value = "";
            }
            el.dispatchEvent(new Event("input", {bubbles: true}));
            el.dispatchEvent(new Event("change", {bubbles: true}));
        """, element)
    _sleep_range(0.15, 0.4)

def _human_type(element, metin: str):
    """Metni insan gibi klavyeden yazıyormuşçasına rastgele gecikmelerle yazar."""
    for char in metin:
        element.send_keys(char)
        _sleep_range(0.03, 0.12, floor=0.01)

def _human_click(driver, element):
    """Gerçek bir fare tıklaması simüle eder (ActionChains ile) ve rastgele bekler."""
    last_error = None
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    _sleep_range(0.25, 0.8)

    click_strategies = (
        lambda: ActionChains(driver).move_to_element(element).click().perform(),
        lambda: element.click(),
        lambda: driver.execute_script("arguments[0].click();", element),
    )
    for strategy in click_strategies:
        try:
            strategy()
            _sleep_range(0.35, 1.0)
            return
        except Exception as e:
            last_error = e

    raise last_error or RuntimeError("Tıklama başarısız")


def _read_element_value(driver, element) -> str:
    try:
        return (driver.execute_script("""
            const el = arguments[0];
            const editable = el.getAttribute("contenteditable");
            if (editable && editable !== "false") {
                return (el.innerText || el.textContent || "").trim();
            }
            return String(el.value ?? el.getAttribute("value") ?? el.innerText ?? el.textContent ?? "").trim();
        """, element) or "").strip()
    except Exception:
        return ""


def _set_element_value_js(driver, element, metin: str):
    driver.execute_script("""
        const el = arguments[0];
        const value = arguments[1];
        const editable = el.getAttribute("contenteditable");

        if (editable && editable !== "false") {
            el.innerHTML = "";
            el.textContent = value;
        } else {
            const prototype = Object.getPrototypeOf(el);
            const descriptor = prototype ? Object.getOwnPropertyDescriptor(prototype, "value") : null;
            if (descriptor && descriptor.set) descriptor.set.call(el, value);
            else el.value = value;
        }

        el.dispatchEvent(new Event("input", {bubbles: true}));
        el.dispatchEvent(new Event("change", {bubbles: true}));
        el.dispatchEvent(new Event("blur", {bubbles: true}));
    """, element, metin)


def _type_into_element(driver, element, metin: str) -> str:
    _focus_and_clear_element(driver, element)
    _human_type(element, metin)
    _sleep_range(0.25, 0.7)

    current_value = _read_element_value(driver, element)
    if _normalize_text(current_value) == _normalize_text(metin):
        return "human_type"

    try:
        _focus_and_clear_element(driver, element)
        element.send_keys(metin)
        _sleep_range(0.15, 0.5)
        current_value = _read_element_value(driver, element)
        if _normalize_text(current_value) == _normalize_text(metin):
            return "send_keys"
    except Exception:
        pass

    _set_element_value_js(driver, element, metin)
    _sleep_range(0.1, 0.3)
    current_value = _read_element_value(driver, element)
    if _normalize_text(current_value) == _normalize_text(metin):
        return "js_fallback"

    raise RuntimeError(f"Yazma dogrulamasi basarisiz. Mevcut deger: '{current_value[:80]}'")

def browser_click_id(element_id: int) -> str:
    """
    browser_dom_oku ile listelenen bir elemanın [ID] numarasına göre tıklar.
    
    Args:
        element_id: Tıklanacak elemanın ID numarası.
    """
    try:
        driver = _get_driver()
        css_selector = f"[data-mar-id='{element_id}']"
        
        target = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
        )
        tag = target.tag_name
        text = (target.text or "").strip()[:40]

        _human_click(driver, target)

        return f"✅ [{element_id}] <{tag}> '{text}' elemanına tıklandı. Yeni sayfa: {driver.title}"
    except Exception as e:
        return f"❌ Tıklama başarısız (ID: {element_id}): {e}"



def browser_click_css(css_selector: str) -> str:
    """
    CSS seçici ile elemana tıklar.
    
    Args:
        css_selector: Tıklanacak elemanın CSS seçicisi (örn: '#login-btn', '.submit').
    """
    try:
        driver = _get_driver()
        el = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
        )
        _human_click(driver, el)
        return f"✅ '{css_selector}' elemanına tıklandı. Yeni sayfa: {driver.title}"
    except Exception as e:
        return f"❌ CSS tıklama başarısız ({css_selector}): {e}"


def browser_bul(sorgu: str, alanlar: str = "text,aria,label,testid,placeholder,title,name,id_attr", limit: int = 8) -> str:
    """
    Görünür etkileşimli elemanlar arasında metin/aria/testid gibi alanlarda arama yapar.
    ID/CSS kırılgan olduğunda önce bu araçla uygun hedefi bul.

    Args:
        sorgu: Aranacak ifade. Örn: 'Giriş Yap', 'E-posta', 'compose'.
        alanlar: Virgülle ayrılmış arama alanları. Varsayılan: text,aria,testid,placeholder,title,name
        limit: En fazla kaç sonuç döneceği.
    """
    try:
        driver = _get_driver()
        allowed_fields = [field.strip().lower() for field in alanlar.split(",") if field.strip()]
        matches = _find_matching_elements(
            driver,
            sorgu=sorgu,
            css_selector=_INTERACTIVE_SELECTOR,
            alanlar=allowed_fields,
            limit=max(1, limit),
            include_disabled=True,
        )
        if not matches:
            return f"❌ '{sorgu}' için görünür eşleşme bulunamadı."

        lines = [f"🔎 '{sorgu}' için {len(matches)} eşleşme bulundu:"]
        for index, (score, _element, fields) in enumerate(matches, start=1):
            confidence = fields.get("_confidence", _score_to_confidence(score))
            lines.append(
                f"  {index}. skor={score} guven={confidence} {_describe_element(fields)}"
            )
            if fields.get("_match_notes"):
                lines.append(f"     eslesme: {', '.join(fields['_match_notes'])}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Arama başarısız: {e}"


def browser_click_text(metin: str) -> str:
    """
    Görünür buton/link/sekme benzeri elemanlar içinde metin, aria-label veya benzeri
    eşleşmeye göre en uygun hedefi bulup tıklar.

    Args:
        metin: Hedef elemanın görünen yazısı veya etiketi. Örn: 'Giriş Yap'
    """
    try:
        driver = _get_driver()
        matches = _find_matching_elements(
            driver,
            sorgu=metin,
            css_selector=(
                "button, a, label, input[type='button'], input[type='submit'], "
                "[role='button'], [role='link'], [role='menuitem'], [role='tab'], [onclick], [tabindex]"
            ),
            alanlar=["text", "aria", "title", "value", "testid", "name"],
            limit=3,
            include_disabled=False,
        )
        if not matches:
            return f"❌ '{metin}' için tıklanabilir görünür eleman bulunamadı."

        errors = []
        for score, target, fields in matches:
            try:
                _human_click(driver, target)
                return (
                    f"✅ Metne göre eleman tıklandı: {_describe_element(fields)} "
                    f"(skor={score}, guven={fields.get('_confidence', _score_to_confidence(score))}). "
                    f"Yeni sayfa: {driver.title}"
                )
            except Exception as candidate_error:
                errors.append(f"{_describe_element(fields)} => {candidate_error}")

        return f"❌ '{metin}' için eşleşmeler bulundu ama tıklanamadı: {' | '.join(errors[:2])}"
    except Exception as e:
        return f"❌ Metne göre tıklama başarısız ({metin}): {e}"


def browser_click_role(rol: str, etiket: str) -> str:
    """
    Belirli bir role sahip elemanlar arasında etikete göre en uygun olanı tıklar.

    Args:
        rol: HTML/ARIA rolü. Örn: 'button', 'link', 'tab', 'menuitem'
        etiket: Hedef elemanın metni veya etiketi. Örn: 'Devam'
    """
    try:
        driver = _get_driver()
        role = (rol or "").strip().lower()
        selector_map = {
            "button": "button, input[type='button'], input[type='submit'], [role='button']",
            "link": "a, [role='link']",
            "tab": "[role='tab']",
            "menuitem": "[role='menuitem']",
            "textbox": "input:not([type='hidden']), textarea, [role='textbox'], [contenteditable]",
        }
        css_selector = selector_map.get(role, f"[role='{role}']")
        matches = _find_matching_elements(
            driver,
            sorgu=etiket,
            css_selector=css_selector,
            alanlar=["text", "aria", "title", "value", "testid", "name"],
            limit=3,
            include_disabled=False,
        )
        if not matches:
            return f"❌ role='{role}' ve etiket='{etiket}' için görünür eleman bulunamadı."

        errors = []
        for score, target, fields in matches:
            try:
                _human_click(driver, target)
                return (
                    f"✅ Role göre eleman tıklandı: {_describe_element(fields)} "
                    f"(skor={score}, guven={fields.get('_confidence', _score_to_confidence(score))}). "
                    f"Yeni sayfa: {driver.title}"
                )
            except Exception as candidate_error:
                errors.append(f"{_describe_element(fields)} => {candidate_error}")

        return f"❌ role='{role}' ve etiket='{etiket}' için adaylar bulundu ama tıklanamadı: {' | '.join(errors[:2])}"
    except Exception as e:
        return f"❌ Role göre tıklama başarısız ({rol}, {etiket}): {e}"


def browser_type_id(element_id: int, metin: str) -> str:
    """
    browser_dom_oku ile listelenen bir input/textarea elemanına metin yazar.
    
    Args:
        element_id: Yazılacak elemanın ID numarası.
        metin: Yazılacak metin.
    """
    try:
        driver = _get_driver()
        css_selector = f"[data-mar-id='{element_id}']"
        
        target = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
        )
        method = _type_into_element(driver, target, metin)
        return f"✅ [{element_id}] elemanına '{metin}' yazıldı. (yontem: {method})"
    except Exception as e:
        return f"❌ Yazma başarısız (ID: {element_id}): {e}"


def browser_type_css(css_selector: str, metin: str) -> str:
    """
    CSS seçici ile bulunan input/textarea elemanına metin yazar.
    
    Args:
        css_selector: Hedef elemanın CSS seçicisi.
        metin: Yazılacak metin.
    """
    try:
        driver = _get_driver()
        el = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
        )
        method = _type_into_element(driver, el, metin)
        _sleep_scaled(0.35)
        return f"✅ '{css_selector}' elemanına '{metin}' yazıldı. (yontem: {method})"
    except Exception as e:
        return f"❌ CSS yazma başarısız ({css_selector}): {e}"


def browser_type_placeholder(placeholder: str, metin: str) -> str:
    """
    Placeholder, aria-label veya benzeri etiketine göre uygun input alanını bulup yazar.

    Args:
        placeholder: Hedef alan etiketi. Örn: 'E-posta', 'Search'
        metin: Yazılacak içerik.
    """
    try:
        driver = _get_driver()
        matches = _find_matching_elements(
            driver,
            sorgu=placeholder,
            css_selector=_TEXT_INPUT_SELECTOR,
            alanlar=["placeholder", "label", "aria", "name", "title", "testid", "id_attr", "text"],
            limit=3,
            include_disabled=False,
        )
        if not matches:
            return f"❌ '{placeholder}' için uygun input alanı bulunamadı."

        errors = []
        for score, target, fields in matches:
            try:
                method = _type_into_element(driver, target, metin)
                return (
                    f"✅ Placeholder/etikete göre yazıldı: {_describe_element(fields)} "
                    f"(skor={score}, guven={fields.get('_confidence', _score_to_confidence(score))}, yontem={method})"
                )
            except Exception as candidate_error:
                errors.append(f"{_describe_element(fields)} => {candidate_error}")

        return f"❌ '{placeholder}' için aday alanlar bulundu ama yazılamadı: {' | '.join(errors[:2])}"
    except Exception as e:
        return f"❌ Placeholder'a göre yazma başarısız ({placeholder}): {e}"


def browser_enter_bas() -> str:
    """Aktif sayfada Enter tuşuna basar. Form göndermek veya arama yapmak için kullanışlıdır."""
    try:
        driver = _get_driver()
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).send_keys(Keys.ENTER).perform()
        _sleep_scaled(0.6)
        return f"✅ Enter tuşuna basıldı. Mevcut sayfa: {driver.title}"
    except Exception as e:
        return f"❌ Enter basılamadı: {e}"


def browser_select_sec(element_id: int, deger: str) -> str:
    """
    Bir <select> (dropdown) elemanından belirtilen değeri seçer.
    Ay, Gün, Yıl gibi dropdown'lar için bu aracı kullan.
    
    Args:
        element_id: browser_dom_oku ile listelenen dropdown'ın [ID] numarası.
        deger: Seçilecek değer. Görünen metin (visible text) veya value attribute olabilir. Örnek: "Ocak", "March", "15"
    """
    try:
        from selenium.webdriver.support.ui import Select
        driver = _get_driver()
        
        elements = driver.find_elements(By.CSS_SELECTOR,
            "a, button, input, textarea, select, [role='button'], [role='link'], "
            "[role='menuitem'], [role='tab'], [onclick], [tabindex]"
        )
        visible = [el for el in elements if _is_visible(el)]

        if element_id < 0 or element_id >= len(visible):
            return f"❌ Geçersiz ID: {element_id}. Toplam {len(visible)} eleman var."

        target = visible[element_id]
        if target.tag_name != "select":
            return f"❌ [{element_id}] bir <select> elemanı değil (<{target.tag_name}>). Bu araç sadece dropdown'lar için."
        
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
        _sleep_scaled(0.3)
        
        select = Select(target)
        
        # Önce visible text ile dene, olmazsa value ile dene
        try:
            select.select_by_visible_text(deger)
        except Exception:
            try:
                select.select_by_value(deger)
            except Exception:
                # Kısmi eşleşme dene
                options = [o.text for o in select.options]
                matched = [o for o in options if deger.lower() in o.lower()]
                if matched:
                    select.select_by_visible_text(matched[0])
                else:
                    return f"❌ '{deger}' bulunamadı. Mevcut seçenekler: {options[:15]}"
        
        selected = select.first_selected_option.text
        return f"✅ [{element_id}] dropdown'dan '{selected}' seçildi."
    except Exception as e:
        return f"❌ Select seçimi başarısız: {e}"


def browser_deger_ata(css_selector: str, deger: str) -> str:
    """
    Bir input elemanının değerini JavaScript ile doğrudan atar.
    Normal send_keys çalışmadığında (özellikle date, hidden input, readonly alanlar) kullan.
    
    Args:
        css_selector: Hedef elemanın CSS seçicisi (örn: 'input[name=\"birthdate\"]').
        deger: Atanacak değer. Tarih alanları için format genellikle 'YYYY-MM-DD'.
    """
    try:
        driver = _get_driver()
        el = driver.find_element(By.CSS_SELECTOR, css_selector)
        
        # JavaScript ile değeri ata ve change event tetikle
        driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
            "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
            el, deger
        )
        _sleep_scaled(0.3)
        
        # Doğrulama
        new_val = el.get_attribute("value")
        return f"✅ '{css_selector}' elemanına '{deger}' değeri atandı. (Mevcut değer: '{new_val}')"
    except Exception as e:
        return f"❌ Değer atama başarısız: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# E) AKILLI BEKLEME (Element-Based Wait)
# ═══════════════════════════════════════════════════════════════════════════════

def browser_eleman_bekle(css_selector: str, timeout: int = 10) -> str:
    """
    Belirtilen CSS seçiciye sahip elemanın sayfada GÖRÜNÜR olmasını bekler.
    AJAX, lazy-load veya animasyonlu içerikler için time.sleep yerine BUNU KULLAN.
    
    Args:
        css_selector: Beklenen elemanın CSS seçicisi.
        timeout: Maksimum bekleme süresi (saniye, varsayılan 10).
    """
    try:
        driver = _get_driver()
        el = WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, css_selector))
        )
        text = (el.text or "").strip()[:50]
        tag = el.tag_name
        return f"✅ Eleman bulundu: <{tag}> '{text}' ({css_selector})"
    except Exception as e:
        return f"❌ {timeout} saniye içinde '{css_selector}' elemanı bulunamadı: {e}"


def browser_bekle(saniye: int = 3) -> str:
    """
    Belirtilen süre kadar bekler. Mümkünse browser_eleman_bekle kullan.
    
    Args:
        saniye: Bekleme süresi (varsayılan 3 saniye).
    """
    _sleep_scaled(saniye)
    return f"✅ {saniye} saniye beklendi."


# ═══════════════════════════════════════════════════════════════════════════════
# F) KAYDIRMA
# ═══════════════════════════════════════════════════════════════════════════════

def browser_scroll(yon: str = "asagi", miktar: int = 500) -> str:
    """
    Sayfayı kaydırır.
    
    Args:
        yon: 'asagi' veya 'yukari' yönde kaydırma.
        miktar: Piksel cinsinden kaydırma miktarı (varsayılan 500).
    """
    try:
        driver = _get_driver()
        if yon == "yukari":
            driver.execute_script(f"window.scrollBy(0, -{miktar});")
        else:
            driver.execute_script(f"window.scrollBy(0, {miktar});")
        _sleep_scaled(0.35)
        return f"✅ Sayfa {miktar}px {yon} kaydırıldı."
    except Exception as e:
        return f"❌ Kaydırma başarısız: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# G) 🍪 COOKİE / OTURUM YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════════════════

def browser_cookie_kaydet(isim: str = "default") -> str:
    """
    Mevcut tarayıcı oturumunun cookie'lerini diske kaydeder.
    Bir sonraki sefere bu siteye girdiğinde cookie_yukle ile oturumu geri yükleyebilirsin.
    
    Args:
        isim: Cookie dosyasının ismi (varsayılan 'default'). Örn: 'twitter'.
    """
    try:
        driver = _get_driver()
        os.makedirs(_COOKIES_DIR, exist_ok=True)
        cookies = driver.get_cookies()
        path = os.path.join(_COOKIES_DIR, f"{isim}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        return f"✅ {len(cookies)} cookie '{path}' dosyasına kaydedildi."
    except Exception as e:
        return f"❌ Cookie kaydetme başarısız: {e}"


def browser_cookie_yukle(isim: str = "default") -> str:
    """
    Daha önce kaydedilmiş cookie'leri tarayıcıya yükler.
    ÖNEMLİ: Cookie yüklemeden ÖNCE ilgili siteye browser_git() ile gitmiş olmalısın.
    
    Args:
        isim: Yüklenecek cookie dosyasının ismi (varsayılan 'default').
    """
    try:
        driver = _get_driver()
        path = os.path.join(_COOKIES_DIR, f"{isim}.json")
        if not os.path.exists(path):
            return f"❌ '{isim}' adında kaydedilmiş cookie bulunamadı."

        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)

        loaded = 0
        for cookie in cookies:
            try:
                # sameSite uyumsuzluk hatalarını önle
                if "sameSite" in cookie and cookie["sameSite"] not in ("Strict", "Lax", "None"):
                    cookie["sameSite"] = "Lax"
                driver.add_cookie(cookie)
                loaded += 1
            except Exception:
                continue

        # Sayfayı yenile ki cookie'ler etkili olsun
        driver.refresh()
        time.sleep(2)
        return f"✅ {loaded}/{len(cookies)} cookie yüklendi ve sayfa yenilendi. Sayfa: {driver.title}"
    except Exception as e:
        return f"❌ Cookie yükleme başarısız: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# H) 📑 SEKME (TAB) YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════════════════

def browser_yeni_sekme(url: str) -> str:
    """
    Yeni bir tarayıcı sekmesinde belirtilen URL'yi açar.
    
    Args:
        url: Açılacak web adresi.
    """
    try:
        driver = _get_driver()
        driver.execute_script(f"window.open('{url}', '_blank');")
        time.sleep(1)
        # Yeni sekmeye geç
        driver.switch_to.window(driver.window_handles[-1])
        time.sleep(1.5)
        return f"✅ Yeni sekmede açıldı: '{driver.title}' ({url}). Toplam {len(driver.window_handles)} sekme."
    except Exception as e:
        return f"❌ Yeni sekme açılamadı: {e}"


def browser_sekme_degistir(index: int) -> str:
    """
    Belirtilen indeksteki sekmeye geçiş yapar.
    
    Args:
        index: Sekme numarası (0'dan başlar). browser_sekme_listele ile görebilirsin.
    """
    try:
        driver = _get_driver()
        handles = driver.window_handles
        if index < 0 or index >= len(handles):
            return f"❌ Geçersiz sekme indeksi: {index}. Toplam {len(handles)} sekme var (0-{len(handles)-1})."
        driver.switch_to.window(handles[index])
        time.sleep(0.5)
        return f"✅ Sekme {index}'e geçildi: '{driver.title}'"
    except Exception as e:
        return f"❌ Sekme değiştirme başarısız: {e}"


def browser_sekme_listele() -> str:
    """Açık tüm sekmeleri listeler. Aktif sekme yıldız (*) ile işaretlenir."""
    try:
        driver = _get_driver()
        handles = driver.window_handles
        current = driver.current_window_handle
        lines = [f"📑 Toplam {len(handles)} sekme:"]
        for i, handle in enumerate(handles):
            driver.switch_to.window(handle)
            marker = " ⭐" if handle == current else ""
            lines.append(f"  [{i}] {driver.title}{marker}")
        # Aktif sekmeye geri dön
        driver.switch_to.window(current)
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Sekmeler listelenemedi: {e}"


def browser_sekme_kapat() -> str:
    """Aktif sekmeyi kapatır ve bir önceki sekmeye geçer."""
    try:
        driver = _get_driver()
        handles = driver.window_handles
        if len(handles) <= 1:
            return "⚠️ Son sekme kapatılamaz. Tarayıcıyı kapatmak için browser_kapat() kullan."
        driver.close()
        time.sleep(0.3)
        driver.switch_to.window(driver.window_handles[-1])
        return f"✅ Sekme kapatıldı. Aktif sekme: '{driver.title}'"
    except Exception as e:
        return f"❌ Sekme kapatma başarısız: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# I) 📥 DOSYA YÜKLEME
# ═══════════════════════════════════════════════════════════════════════════════

def browser_dosya_yukle(css_selector: str, dosya_yolu: str) -> str:
    """
    Sayfadaki bir dosya yükleme alanına (<input type='file'>) dosya gönderir.
    
    Args:
        css_selector: Dosya input elemanının CSS seçicisi.
        dosya_yolu: Yüklenecek dosyanın tam yolu (örn: 'C:/Users/foto.jpg').
    """
    try:
        driver = _get_driver()
        el = driver.find_element(By.CSS_SELECTOR, css_selector)
        abs_path = os.path.abspath(dosya_yolu)
        if not os.path.exists(abs_path):
            return f"❌ Dosya bulunamadı: {abs_path}"
        el.send_keys(abs_path)
        time.sleep(1)
        return f"✅ '{os.path.basename(abs_path)}' dosyası yüklendi."
    except Exception as e:
        return f"❌ Dosya yükleme başarısız: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# J) 🖼️ VLM + BROWSER HİBRİT GÖRSEL ANALİZ
# ═══════════════════════════════════════════════════════════════════════════════

def browser_screenshot() -> bytes:
    """
    Tarayıcının mevcut ekran görüntüsünü PNG formatında döndürür.
    VLM ile birlikte kullanılarak sayfanın görsel analizi yapılabilir.
    """
    try:
        driver = _get_driver()
        png_bytes = driver.get_screenshot_as_png()
        return png_bytes
    except Exception as e:
        return f"❌ Ekran görüntüsü alınamadı: {e}"


async def browser_vlm_yardim(gorev: str) -> str:
    """
    DOM ile başarılamayan görevlerde VLM Agent'ı çağırarak fiziksel ekran etkileşimi yaptırır.
    
    VLM Agent Selenium tarayıcısının ekran görüntüsünü görür ve pyautogui ile fiziksel 
    tıklama/yazma/kaydırma yapar. CAPTCHA, bot koruması gibi durumlarda FİZİKSEL tıklamayı halleder.
    
    Args:
        gorev: VLM Agent'a verilecek NET ve DETAYLI görev açıklaması. Örn: "Ekrandaki mavi butonuna tıkla".
    """
    try:
        driver = _get_driver()
        
        # 1. Selenium'dan tarayıcı ekran görüntüsü al
        png_bytes = driver.get_screenshot_as_png()
        print(f"  🌉 [KÖPRÜ] Browser → VLM: Screenshot alındı, VLM Agent çağrılıyor...")
        
        # 2. VLM Agent'ı registry'den al
        from MarketingApp.llms.SubModels.base import get_submodel
        vlm = get_submodel("vlm_agent")
        
        # 3. VLM Agent'ı async olarak çağır (screenshot + görev gönder)
        enriched_gorev = (
            f"SENİ BROWSER AGENT ÇAĞIRDI. Tarayıcı ekranının görüntüsü aşağıda. "
            f"DOM ile yapılamayan bir işlem var. Görev: {gorev}\n\n"
            f"TALİMAT: Ekran görüntüsünü analiz et, hedefi bul ve pyautogui araçlarıyla "
            f"(click_mouse, type_text, press_key) FİZİKSEL olarak etkileşimde bulun. "
            f"İşlemi tamamladığında sonucu bildir."
        )
        
        result = await vlm.run(gorev=enriched_gorev, image_bytes=png_bytes)
        print(f"  🌉 [KÖPRÜ] VLM → Browser: Sonuç alındı: {str(result)[:150]}")
        
        return f"🌉 VLM Köprü Sonucu: {result}"
    except Exception as e:
        return f"❌ VLM köprüsü başarısız: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# K) TARAYICI KAPATMA
# ═══════════════════════════════════════════════════════════════════════════════

def browser_kapat() -> str:
    """Chrome tarayıcısını kapatır ve kaynakları serbest bırakır."""
    global _driver, _driver_headless
    try:
        if _driver is not None:
            _driver.quit()
            _driver = None
            _driver_headless = None
            return "✅ Tarayıcı kapatıldı."
        return "⚠️ Zaten açık bir tarayıcı yok."
    except Exception as e:
        _driver = None
        _driver_headless = None
        return f"❌ Kapatma hatası: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════════════════════

def _is_visible(el) -> bool:
    """Bir elemanın görünür ve etkileşime açık olup olmadığını kontrol eder."""
    try:
        if not el.is_displayed():
            return False
        size = el.size
        if size.get("width", 0) < 5 or size.get("height", 0) < 5:
            return False
        return True
    except Exception:
        return False

"""
Arama Araçları — Ajanın internet dünyasına açıldığı kapı.
Ücretsiz ve anonim DuckDuckGo üzerinden arama yapar.
"""

try:
    from duckduckgo_search import DDGS
    _DDGS_IMPORT_ERROR = None
except ImportError as ddgs_import_error:
    DDGS = None
    _DDGS_IMPORT_ERROR = ddgs_import_error

def web_arama(sorgu: str, adet: int = 5) -> str:
    """
    İnternette arama yapar ve en alakalı sonuçları döndürür.
    
    Args:
        sorgu: Aranacak kelime veya cümle.
        adet: Kaç sonuç getirileceği (varsayılan: 5).
    """
    if DDGS is None:
        return f"Arama aracı kullanılamıyor: {_DDGS_IMPORT_ERROR}"
    try:
        sonuclar = []
        with DDGS() as ddgs:
            for r in ddgs.text(sorgu, max_results=adet):
                sonuclar.append(f"🔍 {r['title']}\n🔗 {r['href']}\n📄 {r['body']}\n")
        
        if not sonuclar:
            return "Arama sonucunda hiçbir veri bulunamadı."
            
        return "\n".join(sonuclar)
    except Exception as e:
        return f"Arama yapılırken hata oluştu: {str(e)}"

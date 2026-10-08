def metin_ozetle(metin: str, kelime_sayisi: int = 20) -> str:
    try:
        if not metin or not isinstance(metin, str):
            return "Hata: Geçerli bir metin girilmedi."

        kelimeler = metin.split()
        if len(kelimeler) <= kelime_sayisi:
            return metin

        ozet = " ".join(kelimeler[:kelime_sayisi]) + "..."
        return ozet
    except Exception as e:
        return f"İşlem sırasında bir hata oluştu: {str(e)}"

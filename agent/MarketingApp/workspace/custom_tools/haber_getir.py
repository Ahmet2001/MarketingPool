def haber_getir(konu: str, adet: int = 5) -> dict:
    try:
        # Mock veri (gerçek ağ isteği kısıtlaması nedeniyle örnek veri dönüldü)
        haber_veritabanı = {
            "teknoloji": ["Yapay zeka hızla gelişiyor", "Yeni telefon modelleri tanıtıldı", "Yazılım dünyasında büyük değişim", "Siber güvenlik önlemleri", "Bulut bilişim trendleri"],
            "ekonomi": ["Borsa güne düşüşle başladı", "Enflasyon verileri açıklandı", "Altın fiyatlarında son durum", "Merkez bankası kararı", "Yatırım tavsiyeleri"],
            "genel": ["Hava durumu yarın güneşli", "Yerel seçim hazırlıkları", "Yeni eğitim yılı başladı", "Trafik yoğunluğu raporu", "Spor müsabakaları sonuçları"]
        }

        secilen_konu = konu.lower() if konu.lower() in haber_veritabanı else "genel"
        haberler = haber_veritabanı.get(secilen_konu, [])

        sonuc = haberler[:adet]

        return {
            "durum": "başarılı",
            "konu": secilen_konu,
            "haberler": sonuc,
            "toplam": len(sonuc)
        }
    except Exception as e:
        return {"durum": "hata", "mesaj": str(e)}

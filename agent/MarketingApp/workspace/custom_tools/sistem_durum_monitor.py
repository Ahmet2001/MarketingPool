import psutil
import os

def sistem_durum_monitor(detayli: bool = True) -> dict:
    """
    Linux sisteminde CPU ve RAM kullanımını ve (eğer sensör erişimi varsa) sıcaklıkları döner.
    """
    try:
        stats = {
            "cpu_kullanim": f"{psutil.cpu_percent(interval=1)}%",
            "ram_kullanim": f"{psutil.virtual_memory().percent}%",
            "ram_toplam_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        }

        # Sıcaklık kontrolü (Sadece desteklenen sistemlerde)
        if hasattr(psutil, "sensors_temperatures"):
            temp_data = psutil.sensors_temperatures()
            if temp_data:
                stats["sicakliklar"] = {}
                for name, entries in temp_data.items():
                    stats["sicakliklar"][name] = [entry.current for entry in entries]
            else:
                stats["sicakliklar"] = "Sensör verisine erişilemedi."
        else:
            stats["sicakliklar"] = "Sıcaklık sensörü desteği yok."

        if detayli:
            stats["cpu_cekirdek_sayisi"] = psutil.cpu_count()
            stats["ram_kullanilan_gb"] = round(psutil.virtual_memory().used / (1024**3), 2)

        return stats
    except Exception as e:
        return {"hata": f"Sistem verileri okunurken hata oluştu: {str(e)}"}

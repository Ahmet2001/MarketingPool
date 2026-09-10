"""
Terminal Aracı — Sistemin iskelet tuşu.

Bu tek araç sayesinde model:
- Dosya işlemleri: cat, echo, cp, mv, rm, find, grep, mkdir, touch
- Sistem durumu: free -h, df -h, ps aux, top -bn1, nvidia-smi, lsusb
- Görüntü/video: ffmpeg, convert (ImageMagick), python3 PIL
- Kod çalıştırma: python3 script.py, bash script.sh, node index.js
- Paket yönetimi: pip install X, apt-get install -y X, npm install X
- Ağ işlemleri: curl, wget, ping, netstat, ss, ip addr
- Metin işleme: awk, sed, cut, sort, uniq, wc, head, tail, jq
- Arşivleme: tar, zip, unzip, gzip
...her şeyi halledebilir.
"""

import subprocess
import os
import shlex


# Aktif çalışma dizini (session boyunca kalıcı — cd efekti)
_CWD = {"path": os.path.expanduser("~")}


def terminal_komut_calistir(
    komut: str,
    calisma_dizini: str = None,
    zaman_asimi: int = 60,
    stdin_girdi: str = None,
) -> str:
    """
    Shell komutu çalıştırır ve çıktısını döndürür.

    Bu araçla HER ŞEYİ yapabilirsin:
    - Dosya oku/yaz/listele/sil: cat, echo, ls, rm, cp, mv, find, grep, touch, mkdir
    - Sistem durumu: free -h && df -h && ps aux --sort=-%mem | head -10
    - CPU/RAM anlık: top -bn1 | head -20 veya htop --no-color -d 1
    - Video işle: ffmpeg -i input.mp4 -vf scale=1280:720 output.mp4
    - Resim işle: convert input.jpg -resize 50% output.jpg
    - Python çalıştır: python3 -c "import psutil; print(psutil.cpu_percent())"
    - Web indir: curl -sL https://example.com veya wget -q -O - URL
    - JSON işle: cat data.json | jq '.key'
    - Git: git status, git log --oneline -10, git diff
    - cd efekti: cd /path/to/dir && ls -la (bir satırda zincirleme kullanım)
    
    NOT: Birden fazla komutu && veya ; ile zincirleyebilirsin.
    
    Args:
        komut: Çalıştırılacak shell komutu.
        calisma_dizini: Komutun çalışacağı dizin. Boş bırakılırsa son cd'nin dizini.
        zaman_asimi: Saniye cinsinden maksimum süre (varsayılan: 60, max: 600).
        stdin_girdi: Komuta stdin olarak gönderilecek metin (örn. 'y\n' onay için).
    """
    global _CWD

    # Çalışma dizinini belirle
    cwd = calisma_dizini or _CWD["path"]
    if not os.path.isdir(cwd):
        cwd = os.path.expanduser("~")

    # cd komutunu yakala ve state'e kaydet
    stripped = komut.strip()
    if stripped.startswith("cd ") and "&&" not in stripped and ";" not in stripped:
        hedef = stripped[3:].strip().strip('"').strip("'")
        hedef = os.path.expanduser(hedef)
        if not os.path.isabs(hedef):
            hedef = os.path.join(cwd, hedef)
        hedef = os.path.normpath(hedef)
        if os.path.isdir(hedef):
            _CWD["path"] = hedef
            return f"✅ Dizin değişti → {hedef}"
        else:
            return f"❌ Dizin bulunamadı: {hedef}"

    # Zaman aşımı limiti
    zaman_asimi = max(5, min(int(zaman_asimi), 600))

    try:
        proc = subprocess.run(
            komut,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            timeout=zaman_asimi,
            input=stdin_girdi,
        )

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        kod = proc.returncode

        # Çıktı birleştir
        parcalar = []
        if stdout:
            parcalar.append(stdout)
        if stderr:
            parcalar.append(f"[stderr]: {stderr}")

        sonuc = "\n".join(parcalar) if parcalar else "(Çıktı yok)"

        # Çok uzun çıktıyı kırp ama bildir
        LIMIT = 8000
        if len(sonuc) > LIMIT:
            sonuc = sonuc[:LIMIT] + f"\n\n[... {len(sonuc) - LIMIT} karakter kırpıldı. Daha fazla için head/tail kullan.]"

        if kod != 0:
            return f"⚠️ [Çıkış kodu: {kod}] {sonuc}"
        return sonuc

    except subprocess.TimeoutExpired:
        return f"⏱️ Zaman aşımı ({zaman_asimi}s). Uzun işlemler için `zaman_asimi` parametresini artır ya da arka planda çalıştır: `komut &`"
    except Exception as e:
        return f"❌ Terminal hatası: {str(e)}"


def mevcut_dizin() -> str:
    """Şu anki çalışma dizinini döndürür (pwd)."""
    return f"📂 Mevcut dizin: {_CWD['path']}"

def get_system_status() -> str:
    """
    Sistemin anlık durumunu döndürür. Windows/Linux uyumlu.
    CPU kullanımı ve Boş RAM bilgisini içerir.
    """
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        isletim_sistemi = "Windows" if os.name == 'nt' else "Linux"
        
        return (f"📊 Sistem Durumu ({isletim_sistemi}):\n"
                f"CPU Kullanımı: %{cpu}\n"
                f"Boş RAM: {mem.available / (1024**3):.2f} GB / Toplam: {mem.total / (1024**3):.2f} GB")
    except Exception as e:
        return f"Sistem durumu okunamadı: {str(e)}"


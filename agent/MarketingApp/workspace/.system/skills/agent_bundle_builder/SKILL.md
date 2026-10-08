# Agent Bundle Builder

Bu skill, MarketingApp Agent Studio icin disaridan import edilebilir, lego gibi uyumlu
`Tool Pack`, `Agent Bundle` veya `Runtime Pack` uretmek isteyen LLM'lere yoneliktir.

Amac:
- yeni bir tool veya submodel'i serbest bicimde degil,
- MarketingApp'in bekledigi ortak kontrata gore,
- import edilmeye hazir bir paket halinde uretmek.

Bu skill'i kullanan model, ciktiyi "tek dosya fikir notu" olarak degil, gercek klasor
yapisi ve gercek dosya icerigiyle uretmelidir.


## Temel Ilke

Uretecegin paket su ozelliklere sahip olmalidir:

1. Moduler:
   - tool'lar ayri dosyalarda olur
   - agent tanimi ayri manifestte olur
   - env ihtiyaclari ayri listelenir

2. Deterministik:
   - isimlendirme kurallari sabit olur
   - alan adlari standart olur
   - placeholder veya "burayi sonra doldur" tarzi belirsizlik birakilmaz

3. Import Edilebilir:
   - dosya yapisi tek bakista anlasilir
   - bir orchestrator veya Agent Studio loader tarafindan parse edilebilir
   - tool ve agent metadata'si eksiksiz olur

4. Guvenli ve Sinirli:
   - gereksiz dosya yazma, shell komutu veya ag erisimi onermeden once bunu acikca belirt
   - riskli tool'lari `risk: high` olarak isaretle


## Hedef Paket Tipleri

Bu skill yalnizca asagidaki 3 paketten birini uretir:

### 1. Tool Pack
Sadece tool saglar.

Kullan:
- mevcut agent'lara yeni tool eklemek isteniyorsa
- yeni submodel gerekmiyorsa

### 2. Agent Bundle
Config tabanli agent + tool secimi saglar.

Kullan:
- yeni bir uzman ajan isteniyorsa
- o ajanin promptu, modeli ve tool listesi belli ise
- ozel Python runtime davranisi zorunlu degilse

### 3. Runtime Pack
Custom Python submodel + tool'lar saglar.

Kullan:
- sadece prompt/config yeterli degilse
- agent'in kendi runtime mantigi olacaksa
- ileri seviye paket gerekiyorsa


## Zorunlu Klasor Yapisi

Her paket asagidaki kok yapida uretilmelidir:

```text
<pack_name>/
  plugin.yaml
  README.md
  env.example
  tools/
  agents/
  prompts/
  tests/
```

Ek kurallar:
- `pack_name` sadece kucuk harf, rakam ve `_` icersin.
- `pack_name` harfle baslasin.
- bos klasor birakma; kullanilmayan klasorleri acikca not et veya minimal dosya koy.


## plugin.yaml Formati

Her pakette `plugin.yaml` zorunludur.

Asagidaki alanlar bulunmalidir:

```yaml
name: rwa_signal_pack
version: 1
display_name: RWA Signal Pack
kind: agent_bundle
description: RWA ve kurumsal benimseme odakli agent ve tool paketi.
entrypoints:
  agents:
    - agents/rwa_signal_agent.yaml
  tools:
    - tools/rwa_haber_cek.py
dependencies:
  python: []
  env:
    - NEWS_API_KEY
compatibility:
  marketingapp_min_version: 1
risk: medium
```

Kurallar:
- `kind`: `tool_pack`, `agent_bundle` veya `runtime_pack`
- `version`: tam sayi
- `entrypoints.agents`: goreli dosya yollarinin listesi
- `entrypoints.tools`: goreli dosya yollarinin listesi
- `dependencies.python`: pip paket isimleri
- `dependencies.env`: gerekli environment variable adlari
- `risk`: `low`, `medium`, `high`


## Agent Manifest Formati

Config tabanli agent icin `agents/<agent_name>.yaml` kullan.

Ornek:

```yaml
name: rwa_signal_agent
type: config
enabled: true
description: RWA, regulation ve kurumsal benimseme acilarinda icerik ve analiz ajani.
model: default
tool_mode: custom
system_prompt_path: prompts/rwa_signal_agent_system_prompt.md
tools:
  - context_paketi_oku
  - context_aksiyon_kaydet
  - rwa_haber_cek
  - metin_ozetle
memory_tools_recommended:
  - context_paketi_oku
  - context_aksiyon_kaydet
tags:
  - crypto
  - rwa
  - content
```

Kurallar:
- `name` regex: `^[a-z][a-z0-9_]{2,63}$`
- `type`: `config` veya `builtin`
- Disaridan gelen yeni ajanlarda varsayilan `type: config` kullan.
- `system_prompt_path` goreli yol olmali.
- `tools` listesi gercek tool adlarindan olusmali.
- `tool_mode` genelde `custom` olmali.


## Tool Dosyasi Formati

Her tool `tools/<tool_name>.py` dosyasinda tek ana export ile gelmelidir.

Zorunlu kurallar:
- tool adi regex: `^[a-z][a-z0-9_]{2,63}$`
- ana fonksiyon adi dosya adi ile ayni olmali
- fonksiyon `str | dict` donmeli
- docstring icermeli
- argumanlar tip annotation tasimali

Ornek:

```python
from __future__ import annotations

from typing import Any


def rwa_haber_cek(sorgu: str, limit: int = 5) -> dict[str, Any]:
    \"\"\"RWA ile ilgili haber basliklarini getirir.\"\"\"
    sorgu = (sorgu or "").strip()
    if not sorgu:
        raise ValueError("sorgu bos olamaz")

    return {
        "query": sorgu,
        "limit": int(limit),
        "items": [],
    }
```

Ek kurallar:
- gizli global state biriktirme
- import tarafinda yan etki olusturma
- dosya import olur olmaz network cagrisi yapma
- tool cagrilmadan disk yazma


## Runtime Pack Icin Ek Kontrat

Eger `kind: runtime_pack` ise:

- `runtime/` klasoru eklenebilir
- custom submodel `runtime/<agent_name>.py` icinde olur
- sinif, MarketingApp'in submodel mimarisine uyumlu acik bir giris noktasi sunar

Beklenen bilgi:
- sinif adi
- kayit mekanizmasi
- kullandigi tool listesi
- prompt kaynagi

Bu mod sadece gercekten gerekli oldugunda secilmelidir.
Varsayilan tercih `agent_bundle` olmalidir.


## Prompt Dosyasi Kurallari

Her agent prompt'u `prompts/<agent_name>_system_prompt.md` icinde tutulur.

Prompt:
- rol
- karar prensipleri
- tool kullanma sirası
- basari / hata kriterleri
- memory kullanimi

icermelidir.

Prompt'ta sunlar olmamalidir:
- asiri genel pazarlama lafi
- belirsiz "gerektiginde uygun araci kullan" gibi bos cümleler
- gercekten var olmayan tool isimleri


## env.example Kurallari

Eger paket environment variable kullaniyorsa `env.example` zorunludur.

Format:

```env
NEWS_API_KEY=
SERP_API_KEY=
```

Kurallar:
- sadece gereken env'ler yazilsin
- gercek secret yazma
- degisken adlari buyuk harf ve `_` ile olsun


## README.md Icerigi

Her paket README'si su bolumleri icermelidir:

1. Paket amaci
2. Icerdigi tool'lar
3. Icerdigi agent'lar
4. Gerekli env degiskenleri
5. Import sonrasi beklenen kullanim
6. Risk notlari


## Test Beklentisi

Her pakette en az bir `tests/validation_checklist.md` bulunmalidir.

Icerik:
- dosya yapisi tam mi
- plugin.yaml alanlari dolu mu
- tool isimleri manifest ile eslesiyor mu
- agent manifestindeki tool'lar gercekten var mi
- env.example gereken anahtarlari listeliyor mu
- prompt dosyasi var mi


## Uretim Sirasinda Karar Kurallari

Bir paket uretirken su karar sirasini izle:

1. Yeni Python runtime gercekten gerekli mi?
   - hayirsa `agent_bundle`
   - evetse `runtime_pack`

2. Sadece yeni tool mu gerekiyor?
   - evetse `tool_pack`

3. Mevcut tool'lar yeterliyse yeni tool uydurma.

4. Mümkünse su hafiza araclarini oner:
   - `context_paketi_oku`
   - `context_aksiyon_kaydet`

5. Riskli bir dis servis kullaniyorsan:
   - env ekle
   - README'ye not dus
   - `risk` alanini yukselt


## Cikti Formati

Bu skill kullanildiginda model su formatta cikti vermelidir:

1. Kisa ozet
2. Dosya agaci
3. Her dosyanin tam icerigi

Eksik birakma. "istersen devam ederim" deme.


## Hazir Uretim Sablongu

Asagidaki iskeleti kullan:

```text
<pack_name>/
  plugin.yaml
  README.md
  env.example
  agents/
    <agent_name>.yaml
  prompts/
    <agent_name>_system_prompt.md
  tools/
    <tool_name>.py
  tests/
    validation_checklist.md
```


## Son Dogrulama Kontrol Listesi

Uretimi bitirmeden once sunlari kontrol et:

- [ ] Paket tipi net secildi mi?
- [ ] `plugin.yaml` eksiksiz mi?
- [ ] Tum isimler snake_case mi?
- [ ] Tool fonksiyon adlari dosya adlariyla ayni mi?
- [ ] Agent manifestindeki tum tool'lar gercekten mevcut mu?
- [ ] Prompt dosya yolu dogru mu?
- [ ] Env ihtiyaclari `env.example` icinde mi?
- [ ] README import eden kisiye yeterli bilgi veriyor mu?
- [ ] Placeholder, TODO veya sahte API key kaldi mi?


## Bu Skill'in Gorevi

Senin gorevin yaratıcı ama daginik bir cikti vermek degil.
Senin gorevin MarketingApp Agent Studio'ya tak-uyumlu, parse edilebilir,
duzenli ve dogrulanabilir paket uretmek.

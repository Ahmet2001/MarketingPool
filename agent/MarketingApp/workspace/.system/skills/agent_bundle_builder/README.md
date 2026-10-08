# Agent Bundle Builder Skill

Bu klasor, disaridaki bir LLM'e verilecek `SKILL.md` standardini tutar.

Amac:
- kullanicinin "bana yeni agent/tool paketi olustur" istegini,
- serbest formatta degil,
- MarketingApp ile uyumlu paket kontratina gore urettirmek.

Kullanim:
1. Disaridaki modele bu klasordeki `SKILL.md` verilir.
2. Modelden `Tool Pack`, `Agent Bundle` veya `Runtime Pack` uretmesi istenir.
3. Uretilen klasor daha sonra Agent Studio import akisina baglanir.

Not:
Bu skill, mevcut import sistemi tam bitmeden once standardi sabitlemek icin eklendi.
Yani bugunden itibaren paket kontratini tutarli hale getirir; runtime import katmani
ayrica bu kontrata gore gelistirilmelidir.

"""Basit haber basligi ozetleyici ornek custom tool."""

from __future__ import annotations

from collections import Counter
import re


def haber_basliklarini_say(titles: list[str]) -> dict:
    """Verilen basliklar icindeki tekrar eden kelimeleri ve kisa ozeti dondurur."""
    clean_titles = [str(item).strip() for item in (titles or []) if str(item).strip()]
    if not clean_titles:
        return {
            "count": 0,
            "top_words": [],
            "summary": "Baslik listesi bos.",
        }

    words = []
    for title in clean_titles:
        words.extend(
            token.lower()
            for token in re.findall(r"[A-Za-z0-9ÇĞİÖŞÜçğıöşü]+", title)
            if len(token) >= 4
        )

    top_words = Counter(words).most_common(6)
    return {
        "count": len(clean_titles),
        "top_words": top_words,
        "summary": f"{len(clean_titles)} baslik icinde one cikan temalar: "
        + ", ".join(f"{word} ({count})" for word, count in top_words[:4]),
    }

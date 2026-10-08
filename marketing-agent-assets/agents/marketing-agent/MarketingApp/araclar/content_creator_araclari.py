"""
Content creator araçları.

İlk medya kaynakları Pexels API endpointleri üstünden çalışır.
"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from MarketingApp.paths import WORKSPACE_DIR as _WORKSPACE_ROOT

PEXELS_API_BASE = "https://api.pexels.com/v1"
PEXELS_TIMEOUT_SECONDS = 20
WEBSITE_TIMEOUT_SECONDS = 20
_GENERATED_POSTS_ROOT = _WORKSPACE_ROOT / "assets" / "generated_posts"
_GENERATED_VIDEOS_ROOT = _WORKSPACE_ROOT / "assets" / "generated_videos"
_HTML_POSTS_ROOT = _WORKSPACE_ROOT / "content_creator" / "html_posts"
_VIDEO_POSTS_ROOT = _WORKSPACE_ROOT / "content_creator" / "video_posts"
_WEBSITE_PACKAGES_ROOT = _WORKSPACE_ROOT / "drafts" / "content_packages" / "Website"


def _pexels_api_key() -> str:
    env_key = (os.getenv("PEXELS_API_KEY") or "").strip()
    if env_key:
        return env_key

    secrets_path = Path(__file__).resolve().parents[2] / ".env.secrets"
    if not secrets_path.exists():
        return ""
    for line in secrets_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("PEXELS_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def _bounded_per_page(per_page: int) -> int:
    try:
        value = int(per_page)
    except Exception:
        value = 15
    return max(1, min(value, 80))


def _positive_int(value: int, default: int = 1) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, parsed)


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        if isinstance(value, int) and value <= 0:
            continue
        cleaned[key] = value
    return cleaned


def _pexels_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = _pexels_api_key()
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY ortam degiskeni bulunamadi.")

    response = requests.get(
        f"{PEXELS_API_BASE}{path}",
        headers={"Authorization": api_key},
        params=_clean_params(params or {}),
        timeout=PEXELS_TIMEOUT_SECONDS,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text[:1000]}

    if not response.ok:
        message = payload.get("error") if isinstance(payload, dict) else None
        raise RuntimeError(f"Pexels API HTTP {response.status_code}: {message or response.text[:300]}")

    if isinstance(payload, dict):
        payload["_rate_limit"] = {
            "limit": response.headers.get("X-Ratelimit-Limit"),
            "remaining": response.headers.get("X-Ratelimit-Remaining"),
            "reset": response.headers.get("X-Ratelimit-Reset"),
        }
    return payload


def _compact_photo(photo: dict[str, Any]) -> dict[str, Any]:
    src = photo.get("src") or {}
    return {
        "id": photo.get("id"),
        "width": photo.get("width"),
        "height": photo.get("height"),
        "url": photo.get("url"),
        "photographer": photo.get("photographer"),
        "photographer_url": photo.get("photographer_url"),
        "avg_color": photo.get("avg_color"),
        "alt": photo.get("alt"),
        "src": {
            "original": src.get("original"),
            "large2x": src.get("large2x"),
            "large": src.get("large"),
            "medium": src.get("medium"),
            "portrait": src.get("portrait"),
            "landscape": src.get("landscape"),
        },
    }


def _compact_video(video: dict[str, Any]) -> dict[str, Any]:
    user = video.get("user") or {}
    video_files = video.get("video_files") or []
    video_pictures = video.get("video_pictures") or []
    return {
        "id": video.get("id"),
        "width": video.get("width"),
        "height": video.get("height"),
        "duration": video.get("duration"),
        "url": video.get("url"),
        "image": video.get("image"),
        "user": {
            "id": user.get("id"),
            "name": user.get("name"),
            "url": user.get("url"),
        },
        "video_files": [
            {
                "id": item.get("id"),
                "quality": item.get("quality"),
                "file_type": item.get("file_type"),
                "width": item.get("width"),
                "height": item.get("height"),
                "fps": item.get("fps"),
                "link": item.get("link"),
            }
            for item in video_files[:6]
        ],
        "video_pictures": [
            {
                "id": item.get("id"),
                "picture": item.get("picture"),
                "nr": item.get("nr"),
            }
            for item in video_pictures[:4]
        ],
    }


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _bounded_int(value: int, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _safe_url(url: str) -> str:
    text = (url or "").strip()
    if not text:
        raise ValueError("URL bos olamaz.")
    parsed = urlparse(text)
    if not parsed.scheme:
        text = "https://" + text
        parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Gecerli bir http/https URL girilmeli.")
    return text


def _website_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }


def _clean_text(value: str) -> str:
    text = re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()
    return text


def _clip(value: str, limit: int) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _dedupe_texts(values: list[str], min_len: int = 1, limit: int = 50) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = _clean_text(value)
        if len(text) < min_len:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _split_sentences(text: str, limit: int = 8) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", _clean_text(text))
    sentences = []
    for part in parts:
        sentence = _clean_text(part)
        if len(sentence) < 35:
            continue
        sentences.append(_clip(sentence, 240))
        if len(sentences) >= limit:
            break
    return sentences


_KEYWORD_STOPWORDS = {
    "ama", "ancak", "artık", "aslında", "bile", "bir", "bunu", "bu", "çok",
    "daha", "de", "da", "diye", "gibi", "ile", "için", "olan", "olarak",
    "sonra", "şey", "ve", "veya", "ya", "yani", "the", "and", "for", "from",
    "that", "this", "with", "you", "your", "are", "was", "were", "will",
    "our", "their", "have", "has", "not", "but", "can", "into", "about",
}


def _extract_keywords(text: str, limit: int = 12) -> list[str]:
    normalized = _clean_text(text).lower()
    words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9][a-zA-ZçğıöşüÇĞİÖŞÜ0-9-]{2,}", normalized)
    counts: dict[str, int] = {}
    for word in words:
        if word in _KEYWORD_STOPWORDS or len(word) < 3:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:limit]]


def _hashtag(keyword: str) -> str:
    tag = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+", "", keyword.title())
    return f"#{tag}" if tag else ""


def _fit_post(text: str, limit: int = 240) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip(" .,;:") + "…"


def _normalize_platform(platform: str) -> str:
    value = (platform or "x").strip().lower()
    aliases = {
        "twitter": "x",
        "x/twitter": "x",
        "ig": "instagram",
        "linkedin": "linkedin",
        "li": "linkedin",
    }
    return aliases.get(value, value if value in {"x", "instagram", "linkedin"} else "x")


def _extract_site_payload(url: str, max_paragraf: int = 12, max_link: int = 15, max_gorsel: int = 12) -> dict[str, Any]:
    target_url = _safe_url(url)
    max_paragraf = _bounded_int(max_paragraf, 12, 3, 40)
    max_link = _bounded_int(max_link, 15, 0, 50)
    max_gorsel = _bounded_int(max_gorsel, 12, 0, 40)

    response = requests.get(
        target_url,
        headers=_website_headers(),
        timeout=WEBSITE_TIMEOUT_SECONDS,
        allow_redirects=True,
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if content_type and "html" not in content_type and "xml" not in content_type:
        raise RuntimeError(f"URL HTML sayfasi gibi gorunmuyor: {content_type}")

    try:
        from lxml import html as lxml_html
    except Exception as exc:
        raise RuntimeError("lxml paketi yuklu degil; website icerigi parse edilemiyor.") from exc

    doc = lxml_html.fromstring(response.text)
    final_url = response.url
    base_url = final_url

    for node in doc.xpath("//script|//style|//noscript|//svg|//canvas|//iframe|//form"):
        node.drop_tree()

    def first_xpath_text(*queries: str) -> str:
        for query in queries:
            values = doc.xpath(query)
            for value in values:
                if hasattr(value, "text_content"):
                    text = _clean_text(value.text_content())
                else:
                    text = _clean_text(str(value))
                if text:
                    return text
        return ""

    def first_xpath_attr(query: str) -> str:
        values = doc.xpath(query)
        for value in values:
            text = _clean_text(str(value))
            if text:
                return text
        return ""

    title = first_xpath_text(
        "//meta[@property='og:title']/@content",
        "//meta[@name='twitter:title']/@content",
        "//title/text()",
        "//h1[1]",
    )
    description = first_xpath_text(
        "//meta[@name='description']/@content",
        "//meta[@property='og:description']/@content",
        "//meta[@name='twitter:description']/@content",
    )
    canonical = first_xpath_attr("//link[@rel='canonical']/@href")
    canonical = urljoin(base_url, canonical) if canonical else ""
    language = first_xpath_attr("//html/@lang")
    og_image = first_xpath_attr("//meta[@property='og:image']/@content") or first_xpath_attr("//meta[@name='twitter:image']/@content")
    og_image = urljoin(base_url, og_image) if og_image else ""

    roots = doc.xpath("//article|//main|//*[@role='main']")
    root = max(roots, key=lambda item: len(_clean_text(item.text_content())), default=doc)

    headings = []
    for node in root.xpath(".//h1|.//h2|.//h3|.//h4"):
        tag = (node.tag or "").lower()
        text = _clean_text(node.text_content())
        if text:
            headings.append({"level": tag, "text": _clip(text, 180)})
    headings = headings[:24]

    paragraph_candidates = []
    for node in root.xpath(".//p|.//li"):
        text = _clean_text(node.text_content())
        lowered = text.lower()
        if any(marker in lowered for marker in ("cookie", "privacy policy", "all rights reserved", "subscribe to", "newsletter")):
            continue
        paragraph_candidates.append(text)
    paragraphs = [_clip(item, 520) for item in _dedupe_texts(paragraph_candidates, min_len=45, limit=max_paragraf)]

    combined_text = "\n".join([
        title,
        description,
        *[item["text"] for item in headings[:10]],
        *paragraphs,
    ])
    key_points = _split_sentences(" ".join([description, *paragraphs]), limit=8)
    keywords = _extract_keywords(combined_text, limit=12)

    links = []
    seen_links: set[str] = set()
    for node in doc.xpath("//a[@href]"):
        href = _clean_text(node.get("href", ""))
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        text = _clip(node.text_content(), 120)
        if not text or absolute in seen_links:
            continue
        seen_links.add(absolute)
        links.append({"text": text, "url": absolute})
        if len(links) >= max_link:
            break

    images = []
    seen_images: set[str] = set()
    if og_image:
        images.append({"src": og_image, "alt": "og:image", "source": "meta"})
        seen_images.add(og_image)
    for node in doc.xpath("//img[@src or @data-src]"):
        src = _clean_text(node.get("src") or node.get("data-src") or "")
        if not src or src.startswith("data:"):
            continue
        absolute = urljoin(base_url, src)
        if absolute in seen_images:
            continue
        seen_images.add(absolute)
        images.append({
            "src": absolute,
            "alt": _clip(node.get("alt", ""), 140),
            "width": node.get("width"),
            "height": node.get("height"),
            "source": "img",
        })
        if len(images) >= max_gorsel:
            break

    parsed = urlparse(final_url)
    return {
        "status": "ok",
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "url": target_url,
        "final_url": final_url,
        "domain": parsed.netloc,
        "language": language,
        "content_type": content_type,
        "title": title,
        "meta_description": description,
        "canonical_url": canonical,
        "og_image": og_image,
        "headings": headings,
        "paragraphs": paragraphs,
        "key_points": key_points,
        "keywords": keywords,
        "links": links,
        "images": images,
        "content_stats": {
            "heading_count": len(headings),
            "paragraph_count": len(paragraphs),
            "key_point_count": len(key_points),
            "link_count": len(links),
            "image_count": len(images),
            "raw_html_chars": len(response.text),
        },
    }


def _build_website_content_package(
    extracted: dict[str, Any],
    platform: str,
    hedef_kitle: str,
    ton: str,
) -> dict[str, Any]:
    title = extracted.get("title") or extracted.get("domain") or "Web sitesi içeriği"
    description = extracted.get("meta_description") or ""
    key_points = extracted.get("key_points") or extracted.get("paragraphs") or []
    keywords = extracted.get("keywords") or []
    domain = extracted.get("domain") or ""
    platform = _normalize_platform(platform)
    audience = _clean_text(hedef_kitle or "kripto ve teknoloji meraklıları")
    tone = _clean_text(ton or "net, bilgilendirici")
    hashtags = [_hashtag(keyword) for keyword in keywords[:5]]
    hashtags = [tag for tag in hashtags if tag]
    hook_source = description or (key_points[0] if key_points else title)
    hook = _fit_post(f"{title}: {_clip(hook_source, 150)}", 220)
    source_line = f"Kaynak: {domain}" if domain else "Kaynak web site"

    x_post = _fit_post(
        f"{hook}\n\n{source_line} {' '.join(hashtags[:3])}".strip(),
        240,
    )
    thread = [
        _fit_post(f"1/ {title}", 240),
        *[
            _fit_post(f"{idx + 2}/ {point}", 240)
            for idx, point in enumerate(key_points[:4])
        ],
        _fit_post(f"{min(len(key_points[:4]) + 2, 6)}/ Kısa sonuç: Bu konu {audience} için takip edilmeye değer. {source_line}", 240),
    ]
    instagram_caption = "\n\n".join([
        _fit_post(hook, 280),
        "\n".join(f"• {_clip(point, 150)}" for point in key_points[:4]),
        f"Ton: {tone}",
        "Kaydet, sonra tekrar bak.",
        " ".join(hashtags[:8]),
    ]).strip()
    linkedin_post = "\n\n".join([
        hook,
        "Öne çıkan noktalar:",
        "\n".join(f"- {_clip(point, 180)}" for point in key_points[:5]),
        f"Bu içerik özellikle {audience} için anlamlı.",
        source_line,
    ]).strip()

    carousel_slides = [{"slide": 1, "title": _clip(title, 70), "body": _clip(hook_source, 150)}]
    for index, point in enumerate(key_points[:5], start=2):
        carousel_slides.append({
            "slide": index,
            "title": f"Öne çıkan nokta {index - 1}",
            "body": _clip(point, 170),
        })
    carousel_slides.append({
        "slide": len(carousel_slides) + 1,
        "title": "Kısa çıkarım",
        "body": f"{source_line}. Bu başlığı sonraki içeriklerde daha derin açabiliriz.",
    })

    visual_title = _clip(title, 56)
    visual_subtitle = _clip(description or (key_points[0] if key_points else ""), 120)
    stock_query = " ".join(keywords[:3]) or title
    selected_text = {
        "x": x_post,
        "instagram": instagram_caption,
        "linkedin": linkedin_post,
    }.get(platform, x_post)

    return {
        "status": "ok",
        "source": {
            "url": extracted.get("url"),
            "final_url": extracted.get("final_url"),
            "domain": domain,
            "title": title,
            "canonical_url": extracted.get("canonical_url"),
            "og_image": extracted.get("og_image"),
        },
        "strategy": {
            "platform": platform,
            "target_audience": audience,
            "tone": tone,
            "keywords": keywords,
            "hashtags": hashtags,
        },
        "selected_platform_text": selected_text,
        "formats": {
            "x_post": x_post,
            "x_thread": thread,
            "instagram_caption": instagram_caption,
            "linkedin_post": linkedin_post,
            "carousel_slides": carousel_slides,
        },
        "visual_brief": {
            "title": visual_title,
            "subtitle": visual_subtitle,
            "cta": "Detayları keşfet",
            "stock_photo_query": stock_query,
            "suggested_image_url": extracted.get("og_image") or ((extracted.get("images") or [{}])[0].get("src") if extracted.get("images") else ""),
            "platform": platform,
        },
        "raw_material": {
            "meta_description": description,
            "key_points": key_points,
            "headings": extracted.get("headings", [])[:12],
            "links": extracted.get("links", [])[:8],
            "images": extracted.get("images", [])[:8],
        },
    }


def _website_package_to_markdown(package: dict[str, Any]) -> str:
    source = package.get("source", {})
    strategy = package.get("strategy", {})
    formats = package.get("formats", {})
    visual = package.get("visual_brief", {})
    raw = package.get("raw_material", {})

    lines = [
        f"# Website Content Package - {source.get('title') or source.get('domain') or 'Untitled'}",
        "",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- source_url: {source.get('final_url') or source.get('url')}",
        f"- domain: {source.get('domain')}",
        f"- platform: {strategy.get('platform')}",
        f"- audience: {strategy.get('target_audience')}",
        f"- tone: {strategy.get('tone')}",
        "",
        "## Selected Platform Text",
        package.get("selected_platform_text", ""),
        "",
        "## X Post",
        formats.get("x_post", ""),
        "",
        "## X Thread",
        *[f"- {item}" for item in formats.get("x_thread", [])],
        "",
        "## Instagram Caption",
        formats.get("instagram_caption", ""),
        "",
        "## LinkedIn Post",
        formats.get("linkedin_post", ""),
        "",
        "## Carousel Slides",
        *[
            f"- Slide {item.get('slide')}: {item.get('title')} — {item.get('body')}"
            for item in formats.get("carousel_slides", [])
        ],
        "",
        "## Visual Brief",
        f"- title: {visual.get('title')}",
        f"- subtitle: {visual.get('subtitle')}",
        f"- cta: {visual.get('cta')}",
        f"- stock_photo_query: {visual.get('stock_photo_query')}",
        f"- suggested_image_url: {visual.get('suggested_image_url')}",
        "",
        "## Key Points",
        *[f"- {item}" for item in raw.get("key_points", [])],
    ]
    return "\n".join(lines).strip() + "\n"


def _slugify(value: str, fallback: str = "post") -> str:
    text = (value or "").strip().lower()
    text = text.replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text[:80] or fallback


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _clamp_dimension(value: int, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(320, min(parsed, 4096))


def _normalize_hex(value: str, fallback: str) -> str:
    text = (value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.upper()
    return fallback


def _orientation_for_dimensions(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _select_photo_url(photo: dict[str, Any]) -> str:
    src = photo.get("src") or {}
    for key in ("large2x", "large", "original", "landscape", "portrait", "medium"):
        url = src.get(key)
        if url:
            return url
    return ""


def _select_video_file(video: dict[str, Any], target_width: int, target_height: int) -> dict[str, Any]:
    files = [item for item in (video.get("video_files") or []) if item.get("link")]
    if not files:
        return {}

    target_ratio = target_width / max(1, target_height)

    def score(item: dict[str, Any]) -> tuple[int, float, int]:
        width = int(item.get("width") or target_width)
        height = int(item.get("height") or target_height)
        ratio = width / max(1, height)
        quality_penalty = 0 if str(item.get("quality", "")).lower() == "hd" else 600
        type_penalty = 0 if "mp4" in str(item.get("file_type", "")).lower() else 1200
        small_penalty = 900 if width < target_width * 0.75 or height < target_height * 0.75 else 0
        distance = abs(width - target_width) + abs(height - target_height)
        ratio_distance = abs(ratio - target_ratio)
        return (type_penalty + quality_penalty + small_penalty + distance, ratio_distance, -width * height)

    return sorted(files, key=score)[0]


def _extension_from_content_type(content_type: str) -> str:
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    if guessed in {".jpg", ".jpeg", ".png", ".webp"}:
        return ".jpg" if guessed == ".jpeg" else guessed
    return ".jpg"


def _extension_from_video_content_type(content_type: str) -> str:
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    if guessed in {".mp4", ".mov", ".webm", ".m4v"}:
        return guessed
    return ".mp4"


def _download_or_copy_image(image_ref: str, target_dir: Path, filename: str = "stock_photo") -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    ref = (image_ref or "").strip()
    if not ref:
        raise RuntimeError("Indirilecek veya kopyalanacak stok fotoğraf referansı boş.")

    local_path = Path(ref).expanduser()
    if local_path.exists() and local_path.is_file():
        ext = local_path.suffix.lower() if local_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
        target_path = target_dir / f"{filename}{ext}"
        shutil.copyfile(local_path, target_path)
        return target_path

    response = requests.get(ref, timeout=PEXELS_TIMEOUT_SECONDS)
    response.raise_for_status()
    ext = _extension_from_content_type(response.headers.get("Content-Type", ""))
    target_path = target_dir / f"{filename}{ext}"
    target_path.write_bytes(response.content)
    return target_path


def _download_or_copy_video(video_ref: str, target_dir: Path, filename: str = "stock_video") -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    ref = (video_ref or "").strip()
    if not ref:
        raise RuntimeError("Indirilecek veya kopyalanacak stok video referansı boş.")

    local_path = Path(ref).expanduser()
    if local_path.exists() and local_path.is_file():
        ext = local_path.suffix.lower() if local_path.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"} else ".mp4"
        target_path = target_dir / f"{filename}{ext}"
        shutil.copyfile(local_path, target_path)
        return target_path

    response = requests.get(ref, timeout=PEXELS_TIMEOUT_SECONDS, stream=True)
    response.raise_for_status()
    ext = _extension_from_video_content_type(response.headers.get("Content-Type", ""))
    target_path = target_dir / f"{filename}{ext}"
    with open(target_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return target_path


def _image_data_uri(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _render_html_to_png(html_path: Path, output_path: Path, width: int, height: int) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright paketi yuklu degil. requirements.txt kurulumunu kontrol et.") from exc

    launch_errors: list[str] = []
    executable_candidates = [None, "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]

    with sync_playwright() as playwright:
        browser = None
        for executable_path in executable_candidates:
            try:
                kwargs: dict[str, Any] = {"headless": True}
                if executable_path and Path(executable_path).exists():
                    kwargs["executable_path"] = executable_path
                elif executable_path:
                    continue
                browser = playwright.chromium.launch(**kwargs)
                break
            except Exception as exc:
                label = executable_path or "bundled chromium"
                launch_errors.append(f"{label}: {exc}")

        if browser is None:
            raise RuntimeError("Chromium baslatilamadi: " + " | ".join(launch_errors[-3:]))

        try:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.locator(".post").screenshot(path=str(output_path))
        finally:
            browser.close()


def _clamp_video_duration(value: int, default: int = 8) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(2, min(parsed, 60))


def _font_file() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return candidates[0]


def _wrap_overlay_text(text: str, max_chars: int, max_lines: int) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    words = cleaned.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = lines[-1].rstrip(" .,;:") + "..."
    return "\n".join(lines)


def _ffmpeg_color(hex_color: str, fallback: str = "#00F0FF") -> str:
    normalized = _normalize_hex(hex_color, fallback)
    return "0x" + normalized.lstrip("#")


def _run_subprocess(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _render_video_to_mp4(
    *,
    input_path: Path,
    output_path: Path,
    artifact_dir: Path,
    width: int,
    height: int,
    duration: int,
    title: str,
    subtitle: str,
    cta: str,
    brand: str,
    platform: str,
    accent: str,
    secondary: str,
) -> dict[str, Any]:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg bulunamadı. Video render için ffmpeg gerekli.")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_file = _font_file()
    scale = max(0.55, min(width / 1080, height / 1920 if height > width else height / 1080))
    pad = max(34, int(min(width, height) * 0.055))
    title_size = max(38, int(min(width, height) * 0.075))
    subtitle_size = max(24, int(min(width, height) * 0.038))
    cta_size = max(24, int(min(width, height) * 0.036))
    brand_size = max(20, int(min(width, height) * 0.03))
    title_max_chars = max(14, int(width / max(1, title_size) * 1.55))
    subtitle_max_chars = max(22, int(width / max(1, subtitle_size) * 1.65))

    text_files = {
        "brand": artifact_dir / "brand.txt",
        "platform": artifact_dir / "platform.txt",
        "title": artifact_dir / "title.txt",
        "subtitle": artifact_dir / "subtitle.txt",
        "cta": artifact_dir / "cta.txt",
    }
    text_files["brand"].write_text(_wrap_overlay_text(brand or "Mimar", 28, 1), encoding="utf-8")
    text_files["platform"].write_text(_wrap_overlay_text((platform or "SOCIAL").upper(), 24, 1), encoding="utf-8")
    text_files["title"].write_text(_wrap_overlay_text(title or "Sosyal Video", title_max_chars, 3), encoding="utf-8")
    text_files["subtitle"].write_text(_wrap_overlay_text(subtitle, subtitle_max_chars, 3), encoding="utf-8")
    text_files["cta"].write_text(_wrap_overlay_text(cta, 32, 1), encoding="utf-8")

    content_y = int(height * 0.56)
    title_y = content_y + pad
    subtitle_y = title_y + int(title_size * 3.25)
    cta_y = min(height - pad - cta_size * 2, subtitle_y + int(subtitle_size * 3.65))
    accent_color = _ffmpeg_color(accent, "#00F0FF")
    secondary_color = _ffmpeg_color(secondary, "#F7931A")

    chain = ",".join([
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        f"trim=duration={duration}",
        "setpts=PTS-STARTPTS",
        "setsar=1",
        "format=rgba",
        "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.28:t=fill",
        f"drawbox=x=0:y={int(height * 0.52)}:w=iw:h={int(height * 0.48)}:color=black@0.55:t=fill",
        f"drawbox=x={pad}:y={pad}:w={max(170, int(width * 0.20))}:h={max(42, int(brand_size * 1.9))}:color=black@0.34:t=fill",
        f"drawtext=fontfile={font_file}:textfile={text_files['brand']}:fontcolor=white:fontsize={brand_size}:x={pad + 18}:y={pad + 12}:line_spacing=4",
        f"drawtext=fontfile={font_file}:textfile={text_files['platform']}:fontcolor={accent_color}:fontsize={brand_size}:x={pad}:y={max(pad * 2 + brand_size, content_y - int(brand_size * 1.8))}:line_spacing=4",
        f"drawtext=fontfile={font_file}:textfile={text_files['title']}:fontcolor=white:fontsize={title_size}:x={pad}:y={title_y}:line_spacing={max(8, int(title_size * 0.18))}:shadowcolor=black@0.55:shadowx=3:shadowy=3",
        f"drawtext=fontfile={font_file}:textfile={text_files['subtitle']}:fontcolor=white@0.82:fontsize={subtitle_size}:x={pad}:y={subtitle_y}:line_spacing={max(6, int(subtitle_size * 0.22))}",
        f"drawbox=x={pad}:y={cta_y}:w={max(220, int(width * 0.30))}:h={max(54, int(cta_size * 2.15))}:color={secondary_color}@0.88:t=fill",
        f"drawtext=fontfile={font_file}:textfile={text_files['cta']}:fontcolor=black:fontsize={cta_size}:x={pad + 22}:y={cta_y + int(cta_size * 0.55)}:line_spacing=4",
        "format=yuv420p",
    ])
    filter_script = artifact_dir / "video_filter.txt"
    filter_script.write_text(f"[0:v]{chain}[v]\n", encoding="utf-8")

    command = [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(input_path),
        "-t",
        str(duration),
        "-filter_complex_script",
        str(filter_script),
        "-map",
        "[v]",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        completed = _run_subprocess(command)
    except subprocess.CalledProcessError as exc:
        error_text = (exc.stderr or exc.stdout or str(exc))[-1800:]
        raise RuntimeError(f"FFmpeg render hatası: {error_text}") from exc

    return {
        "filter_script_path": str(filter_script.resolve()),
        "ffmpeg_stderr_tail": (completed.stderr or "")[-800:],
        "text_files": {key: str(value.resolve()) for key, value in text_files.items()},
    }


def _build_post_html(
    *,
    width: int,
    height: int,
    title: str,
    subtitle: str,
    cta: str,
    brand: str,
    note: str,
    platform: str,
    accent: str,
    secondary: str,
    image_data_uri: str,
    photographer: str,
    pexels_url: str,
) -> tuple[str, str]:
    scale = max(0.55, min(width / 1600, height / 900))
    title_size = max(42, int(88 * scale))
    subtitle_size = max(24, int(34 * scale))
    cta_size = max(20, int(26 * scale))
    pad = max(44, int(80 * scale))
    title_html = html.escape(title.strip() or "Dikkat Cekici Post")
    subtitle_html = html.escape(subtitle.strip())
    cta_html = html.escape(cta.strip())
    brand_html = html.escape(brand.strip() or "Mimar")
    note_html = html.escape(note.strip())
    platform_html = html.escape(platform.strip().upper() or "SOCIAL")
    credit_html = html.escape(f"Photo: {photographer} / Pexels" if photographer else "Photo: Pexels")
    pexels_url_html = html.escape(pexels_url or "")

    css = f"""
:root {{
  --accent: {accent};
  --secondary: {secondary};
  --ink: #f8fbff;
  --muted: rgba(248, 251, 255, 0.72);
  --panel: rgba(6, 9, 14, 0.68);
}}

* {{
  box-sizing: border-box;
}}

html,
body {{
  width: {width}px;
  height: {height}px;
  margin: 0;
  overflow: hidden;
  background: #06090e;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}

.post {{
  position: relative;
  width: {width}px;
  height: {height}px;
  overflow: hidden;
  color: var(--ink);
  background: #06090e;
}}

.photo {{
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scale(1.035);
  filter: saturate(1.08) contrast(1.04);
}}

.overlay {{
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 78% 20%, color-mix(in srgb, var(--accent) 34%, transparent), transparent 34%),
    linear-gradient(90deg, rgba(4, 7, 12, 0.96) 0%, rgba(4, 7, 12, 0.78) 46%, rgba(4, 7, 12, 0.26) 100%),
    linear-gradient(0deg, rgba(4, 7, 12, 0.82), rgba(4, 7, 12, 0.08) 52%, rgba(4, 7, 12, 0.65));
}}

.grain {{
  position: absolute;
  inset: 0;
  opacity: 0.16;
  background-image:
    linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px);
  background-size: {max(22, int(36 * scale))}px {max(22, int(36 * scale))}px;
  mask-image: linear-gradient(90deg, black, transparent 82%);
}}

.brand {{
  position: absolute;
  top: {pad}px;
  left: {pad}px;
  display: flex;
  align-items: center;
  gap: {max(12, int(14 * scale))}px;
  font-size: {max(18, int(23 * scale))}px;
  font-weight: 800;
  letter-spacing: 0;
}}

.brand::before {{
  content: "";
  width: {max(18, int(24 * scale))}px;
  height: {max(18, int(24 * scale))}px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--accent), var(--secondary));
  box-shadow: 0 0 {max(18, int(34 * scale))}px color-mix(in srgb, var(--accent) 55%, transparent);
}}

.content {{
  position: absolute;
  left: {pad}px;
  bottom: {pad}px;
  width: min({max(520, int(width * 0.58))}px, calc(100% - {pad * 2}px));
}}

.kicker {{
  display: inline-flex;
  align-items: center;
  min-height: {max(34, int(46 * scale))}px;
  padding: 0 {max(18, int(24 * scale))}px;
  border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
  border-radius: {max(6, int(8 * scale))}px;
  background: rgba(0, 0, 0, 0.34);
  color: var(--accent);
  font-size: {max(16, int(20 * scale))}px;
  font-weight: 900;
  letter-spacing: 0;
}}

h1 {{
  max-width: 100%;
  margin: {max(18, int(26 * scale))}px 0 {max(18, int(24 * scale))}px;
  font-size: {title_size}px;
  line-height: 0.95;
  letter-spacing: 0;
  text-wrap: balance;
  overflow-wrap: anywhere;
  text-shadow: 0 {max(8, int(16 * scale))}px {max(20, int(48 * scale))}px rgba(0, 0, 0, 0.62);
}}

.subtitle {{
  max-width: {max(480, int(width * 0.52))}px;
  margin: 0;
  color: var(--muted);
  font-size: {subtitle_size}px;
  line-height: 1.26;
  overflow-wrap: anywhere;
}}

.cta-row {{
  display: flex;
  align-items: center;
  gap: {max(14, int(18 * scale))}px;
  margin-top: {max(24, int(34 * scale))}px;
}}

.cta {{
  display: {"inline-flex" if cta_html else "none"};
  align-items: center;
  min-height: {max(44, int(60 * scale))}px;
  padding: 0 {max(24, int(34 * scale))}px;
  border-radius: {max(7, int(9 * scale))}px;
  background: linear-gradient(135deg, var(--accent), var(--secondary));
  color: #061017;
  font-size: {cta_size}px;
  font-weight: 950;
  letter-spacing: 0;
  box-shadow: 0 {max(14, int(24 * scale))}px {max(32, int(58 * scale))}px rgba(0, 0, 0, 0.36);
  white-space: normal;
  overflow-wrap: anywhere;
}}

.line {{
  flex: 1;
  max-width: {max(120, int(220 * scale))}px;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent);
}}

.note {{
  display: {"block" if note_html else "none"};
  margin-top: {max(20, int(28 * scale))}px;
  color: rgba(248, 251, 255, 0.66);
  font-size: {max(17, int(21 * scale))}px;
  line-height: 1.3;
}}

.credit {{
  position: absolute;
  right: {max(22, int(34 * scale))}px;
  bottom: {max(18, int(24 * scale))}px;
  max-width: {max(260, int(width * 0.34))}px;
  color: rgba(248, 251, 255, 0.54);
  font-size: {max(12, int(15 * scale))}px;
  line-height: 1.25;
  text-align: right;
  overflow-wrap: anywhere;
}}
"""

    document = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width={width}, initial-scale=1">
  <title>{title_html}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main class="post" aria-label="Generated social post">
    <img class="photo" src="{image_data_uri}" alt="">
    <div class="overlay"></div>
    <div class="grain"></div>
    <div class="brand">{brand_html}</div>
    <section class="content">
      <div class="kicker">{platform_html}</div>
      <h1>{title_html}</h1>
      <p class="subtitle">{subtitle_html}</p>
      <div class="cta-row">
        <div class="cta">{cta_html}</div>
        <div class="line"></div>
      </div>
      <div class="note">{note_html}</div>
    </section>
    <div class="credit" data-source="{pexels_url_html}">{credit_html}</div>
  </main>
</body>
</html>
"""
    return document, css


def website_icerik_cikar(url: str, max_paragraf: int = 12, max_link: int = 15, max_gorsel: int = 12) -> str:
    """
    Verilen web sitesinden temiz içerik çıkarır.

    Başlık, meta açıklama, ana heading'ler, paragraf özetleri, önemli linkler,
    görseller, og:image, anahtar kelimeler ve post üretimine uygun key point listesi döndürür.

    Args:
        url: İçeriği çıkarılacak web sitesi URL'si.
        max_paragraf: Döndürülecek maksimum paragraf/özet parçası.
        max_link: Döndürülecek maksimum link sayısı.
        max_gorsel: Döndürülecek maksimum görsel sayısı.
    """
    try:
        payload = _extract_site_payload(
            url=url,
            max_paragraf=max_paragraf,
            max_link=max_link,
            max_gorsel=max_gorsel,
        )
        payload["usage"] = (
            "Bu çıktıyı caption, thread, carousel, görsel brief veya PNG post üretimi için ham malzeme olarak kullan."
        )
        return _json_result(payload)
    except Exception as e:
        return f"❌ Website içerik çıkarma hatası: {e}"


def website_iceriginden_post_paketi_uret(
    url: str,
    platform: str = "x",
    hedef_kitle: str = "",
    ton: str = "net, bilgilendirici",
    workspace_kaydet: bool = True,
) -> str:
    """
    Verilen web sitesini okuyup sosyal medya içerik paketine dönüştürür.

    X postu, X thread, Instagram caption, LinkedIn post, carousel slide akışı ve
    HTML/CSS PNG üretimine verilebilecek görsel brief hazırlar. İstenirse paketi
    workspace/drafts/content_packages/Website içine Markdown olarak kaydeder.

    Args:
        url: İçeriği çıkarılacak web sitesi URL'si.
        platform: Ana hedef platform: x, instagram veya linkedin.
        hedef_kitle: İçeriğin konuşacağı kitle.
        ton: Yazım tonu.
        workspace_kaydet: True ise üretilen içerik paketini Markdown olarak kaydeder.
    """
    try:
        extracted = _extract_site_payload(url=url, max_paragraf=14, max_link=18, max_gorsel=12)
        package = _build_website_content_package(
            extracted=extracted,
            platform=platform,
            hedef_kitle=hedef_kitle,
            ton=ton,
        )

        saved_path = ""
        if bool(workspace_kaydet):
            _WEBSITE_PACKAGES_ROOT.mkdir(parents=True, exist_ok=True)
            source_title = package.get("source", {}).get("title") or package.get("source", {}).get("domain") or "website_package"
            filename = f"{_slugify(source_title, 'website_package')}_{_timestamp()}.md"
            target_path = _WEBSITE_PACKAGES_ROOT / filename
            target_path.write_text(_website_package_to_markdown(package), encoding="utf-8")
            saved_path = str(target_path.resolve())

        package["workspace_markdown_path"] = saved_path
        package["usage"] = (
            "selected_platform_text doğrudan kullanılabilir; visual_brief alanı "
            "html_css_post_olustur_ve_png_kaydet aracına brief olarak verilebilir."
        )
        return _json_result(package)
    except Exception as e:
        return f"❌ Website post paketi üretme hatası: {e}"


def pexels_fotograf_ara(
    query: str,
    orientation: str = "",
    size: str = "",
    color: str = "",
    locale: str = "",
    page: int = 1,
    per_page: int = 15,
) -> str:
    """
    Pexels GET /v1/search endpoint'i ile query'e göre fotoğraf arar.

    Args:
        query: Aranacak konu. Ornek: bitcoin, office, nature.
        orientation: landscape, portrait veya square.
        size: large, medium veya small.
        color: Renk adi veya HEX degeri.
        locale: Dil/bolge kodu. Ornek: tr-TR, en-US.
        page: Sayfa numarasi.
        per_page: Sayfa basina sonuc sayisi, en fazla 80.
    """
    try:
        data = _pexels_get(
            "/search",
            {
                "query": query,
                "orientation": orientation,
                "size": size,
                "color": color,
                "locale": locale,
                "page": _positive_int(page),
                "per_page": _bounded_per_page(per_page),
            },
        )
        return _json_result(
            {
                "endpoint": "GET /v1/search",
                "query": query,
                "page": data.get("page"),
                "per_page": data.get("per_page"),
                "total_results": data.get("total_results"),
                "next_page": data.get("next_page"),
                "photos": [_compact_photo(photo) for photo in data.get("photos", [])],
                "attribution_required": "Pexels ve fotografci linkini gorunur bicimde belirt.",
                "rate_limit": data.get("_rate_limit"),
            }
        )
    except Exception as e:
        return f"❌ Pexels fotoğraf arama hatası: {e}"


def pexels_curated_fotograflar(page: int = 1, per_page: int = 15) -> str:
    """
    Pexels GET /v1/curated endpoint'i ile Pexels ekibinin seçtiği fotoğrafları getirir.

    Args:
        page: Sayfa numarasi.
        per_page: Sayfa basina sonuc sayisi, en fazla 80.
    """
    try:
        data = _pexels_get(
            "/curated",
            {
                "page": _positive_int(page),
                "per_page": _bounded_per_page(per_page),
            },
        )
        return _json_result(
            {
                "endpoint": "GET /v1/curated",
                "page": data.get("page"),
                "per_page": data.get("per_page"),
                "total_results": data.get("total_results"),
                "next_page": data.get("next_page"),
                "photos": [_compact_photo(photo) for photo in data.get("photos", [])],
                "attribution_required": "Pexels ve fotografci linkini gorunur bicimde belirt.",
                "rate_limit": data.get("_rate_limit"),
            }
        )
    except Exception as e:
        return f"❌ Pexels curated fotoğraf hatası: {e}"


def pexels_fotograf_detay(photo_id: int) -> str:
    """
    Pexels GET /v1/photos/{id} endpoint'i ile tekil fotoğraf detayı getirir.

    Args:
        photo_id: Pexels fotograf ID degeri.
    """
    try:
        data = _pexels_get(f"/photos/{int(photo_id)}")
        return _json_result(
            {
                "endpoint": "GET /v1/photos/{id}",
                "photo": _compact_photo(data),
                "attribution_required": "Pexels ve fotografci linkini gorunur bicimde belirt.",
                "rate_limit": data.get("_rate_limit"),
            }
        )
    except Exception as e:
        return f"❌ Pexels fotoğraf detay hatası: {e}"


def pexels_video_ara(
    query: str,
    orientation: str = "",
    size: str = "",
    locale: str = "",
    page: int = 1,
    per_page: int = 15,
) -> str:
    """
    Pexels GET /v1/videos/search endpoint'i ile query'e göre video arar.

    Args:
        query: Aranacak konu. Ornek: city, bitcoin, trading.
        orientation: landscape, portrait veya square.
        size: large, medium veya small.
        locale: Dil/bolge kodu. Ornek: tr-TR, en-US.
        page: Sayfa numarasi.
        per_page: Sayfa basina sonuc sayisi, en fazla 80.
    """
    try:
        data = _pexels_get(
            "/videos/search",
            {
                "query": query,
                "orientation": orientation,
                "size": size,
                "locale": locale,
                "page": _positive_int(page),
                "per_page": _bounded_per_page(per_page),
            },
        )
        return _json_result(
            {
                "endpoint": "GET /v1/videos/search",
                "query": query,
                "page": data.get("page"),
                "per_page": data.get("per_page"),
                "total_results": data.get("total_results"),
                "next_page": data.get("next_page"),
                "videos": [_compact_video(video) for video in data.get("videos", [])],
                "attribution_required": "Pexels ve video sahibi linkini gorunur bicimde belirt.",
                "rate_limit": data.get("_rate_limit"),
            }
        )
    except Exception as e:
        return f"❌ Pexels video arama hatası: {e}"


def pexels_populer_videolar(
    min_width: int = 0,
    min_height: int = 0,
    min_duration: int = 0,
    max_duration: int = 0,
    page: int = 1,
    per_page: int = 15,
) -> str:
    """
    Pexels GET /v1/videos/popular endpoint'i ile popüler videoları getirir.

    Args:
        min_width: Minimum video genisligi.
        min_height: Minimum video yuksekligi.
        min_duration: Minimum sure, saniye.
        max_duration: Maksimum sure, saniye.
        page: Sayfa numarasi.
        per_page: Sayfa basina sonuc sayisi, en fazla 80.
    """
    try:
        data = _pexels_get(
            "/videos/popular",
            {
                "min_width": int(min_width),
                "min_height": int(min_height),
                "min_duration": int(min_duration),
                "max_duration": int(max_duration),
                "page": _positive_int(page),
                "per_page": _bounded_per_page(per_page),
            },
        )
        return _json_result(
            {
                "endpoint": "GET /v1/videos/popular",
                "page": data.get("page"),
                "per_page": data.get("per_page"),
                "total_results": data.get("total_results"),
                "next_page": data.get("next_page"),
                "videos": [_compact_video(video) for video in data.get("videos", [])],
                "attribution_required": "Pexels ve video sahibi linkini gorunur bicimde belirt.",
                "rate_limit": data.get("_rate_limit"),
            }
        )
    except Exception as e:
        return f"❌ Pexels popüler video hatası: {e}"


def video_post_olustur_ve_mp4_kaydet(
    baslik: str,
    alt_baslik: str = "",
    cta: str = "",
    stok_video_query: str = "",
    stok_video_url: str = "",
    platform: str = "reels",
    genislik: int = 1080,
    yukseklik: int = 1920,
    sure_saniye: int = 8,
    marka: str = "Mimar",
    vurgu_rengi: str = "#00F0FF",
    ikincil_renk: str = "#F7931A",
    cikti_adi: str = "",
    ara_dosyalari_sil: bool = True,
) -> str:
    """
    Stok video veya yerel MP4 üstüne metin bindirir, sosyal medya formatında MP4 kaydeder.

    Video kaynağı önceliği:
    1. stok_video_url verilirse direkt o URL veya yerel video dosyası kullanılır.
    2. stok_video_query verilirse Pexels GET /v1/videos/search ile uygun stok video aranır.
    3. Hiçbiri verilmezse başlık video arama sorgusu olarak kullanılır.

    Args:
        baslik: Videoda gösterilecek ana başlık.
        alt_baslik: Başlık altı destek metni.
        cta: CTA etiketi. Boşsa varsayılan kısa CTA kullanılır.
        stok_video_query: Pexels video arama sorgusu.
        stok_video_url: Hazır stok video URL'si veya yerel MP4/MOV/WebM yolu.
        platform: reels, shorts, tiktok, x, youtube, instagram gibi çıktı etiketi.
        genislik: MP4 genişliği. Reels/Shorts için 1080 önerilir.
        yukseklik: MP4 yüksekliği. Reels/Shorts için 1920 önerilir.
        sure_saniye: Çıktı süresi, 2-60 saniye arası.
        marka: Sol üst marka/metin.
        vurgu_rengi: Platform etiketi rengi, HEX.
        ikincil_renk: CTA kutusu rengi, HEX.
        cikti_adi: Dosya adı slug'ı. Boşsa başlıktan üretilir.
        ara_dosyalari_sil: True ise render sonrası geçici video, text ve filter dosyalarını siler.
    """
    try:
        width = _clamp_dimension(genislik, 1080)
        height = _clamp_dimension(yukseklik, 1920)
        duration = _clamp_video_duration(sure_saniye, 8)
        accent = _normalize_hex(vurgu_rengi, "#00F0FF")
        secondary = _normalize_hex(ikincil_renk, "#F7931A")
        effective_cta = cta.strip() if cta and cta.strip() else "Detayları keşfet"
        base_slug = _slugify(cikti_adi or baslik or stok_video_query, "video_post")
        run_slug = f"{base_slug}_{_timestamp()}"
        artifact_dir = _VIDEO_POSTS_ROOT / run_slug
        assets_dir = artifact_dir / "assets"
        output_dir = _GENERATED_VIDEOS_ROOT
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        video_ref = (stok_video_url or "").strip()
        video_metadata: dict[str, Any] = {}
        selected_file: dict[str, Any] = {}
        source_kind = "direct_url" if video_ref else "pexels_video_search"

        if not video_ref:
            query = (stok_video_query or baslik or "social media background").strip()
            selected = _pexels_get(
                "/videos/search",
                {
                    "query": query,
                    "orientation": _orientation_for_dimensions(width, height),
                    "per_page": 8,
                    "page": 1,
                },
            )
            videos = selected.get("videos", [])
            if not videos:
                raise RuntimeError(f"Pexels video aramasinda sonuc bulunamadi: {query}")

            target_ratio = width / max(1, height)

            def video_score(video: dict[str, Any]) -> tuple[float, int]:
                video_width = int(video.get("width") or width)
                video_height = int(video.get("height") or height)
                ratio = video_width / max(1, video_height)
                duration_penalty = 0 if int(video.get("duration") or 0) >= duration else 4
                return (abs(ratio - target_ratio) + duration_penalty, -video_width * video_height)

            selected_video = sorted(videos, key=video_score)[0]
            selected_file = _select_video_file(selected_video, width, height)
            if not selected_file:
                raise RuntimeError("Pexels sonucunda indirilebilir video dosyasi bulunamadi.")
            video_metadata = _compact_video(selected_video)
            video_ref = selected_file.get("link", "")
        else:
            video_metadata = {
                "id": None,
                "url": video_ref,
                "video_files": [{"link": video_ref}],
            }
            selected_file = {"link": video_ref}

        if not video_ref:
            raise RuntimeError("Stok video URL'si seçilemedi.")

        local_video = _download_or_copy_video(video_ref, assets_dir)
        mp4_path = output_dir / f"{run_slug}.mp4"
        render_info = _render_video_to_mp4(
            input_path=local_video,
            output_path=mp4_path,
            artifact_dir=artifact_dir,
            width=width,
            height=height,
            duration=duration,
            title=baslik,
            subtitle=alt_baslik,
            cta=effective_cta,
            brand=marka,
            platform=platform,
            accent=accent,
            secondary=secondary,
        )

        metadata_path = artifact_dir / "metadata.json"
        metadata = {
            "title": baslik,
            "subtitle": alt_baslik,
            "cta": effective_cta,
            "platform": platform,
            "width": width,
            "height": height,
            "duration_seconds": duration,
            "accent": accent,
            "secondary": secondary,
            "source_kind": source_kind,
            "video": video_metadata,
            "selected_video_file": selected_file,
            "stock_video_path": str(local_video.resolve()),
            "mp4_path": str(mp4_path.resolve()),
            "render_info": render_info,
            "attribution_required": "Pexels ve video sahibi linkini post metninde veya açıklamada belirt.",
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        intermediate_deleted = False
        deleted_paths: list[str] = []
        if bool(ara_dosyalari_sil):
            deleted_paths = [str(local_video.resolve()), str(metadata_path.resolve())]
            for value in render_info.get("text_files", {}).values():
                deleted_paths.append(value)
            if render_info.get("filter_script_path"):
                deleted_paths.append(str(render_info["filter_script_path"]))
            shutil.rmtree(artifact_dir, ignore_errors=True)
            intermediate_deleted = not artifact_dir.exists()

        return _json_result(
            {
                "status": "ok",
                "message": "Stok videolu sosyal medya postu MP4 olarak kaydedildi.",
                "mp4_path": str(mp4_path.resolve()),
                "metadata_path": None if intermediate_deleted else str(metadata_path.resolve()),
                "stock_video_path": None if intermediate_deleted else str(local_video.resolve()),
                "intermediate_files_deleted": intermediate_deleted,
                "deleted_intermediate_paths": deleted_paths if intermediate_deleted else [],
                "dimensions": {"width": width, "height": height},
                "duration_seconds": duration,
                "video": video_metadata,
                "selected_video_file": selected_file,
                "attribution_required": metadata["attribution_required"],
            }
        )
    except Exception as e:
        return f"❌ Video post MP4 oluşturma hatası: {e}"


def html_css_post_olustur_ve_png_kaydet(
    baslik: str,
    alt_baslik: str = "",
    cta: str = "",
    stok_fotograf_query: str = "",
    stok_fotograf_url: str = "",
    pexels_photo_id: int = 0,
    platform: str = "x",
    genislik: int = 1600,
    yukseklik: int = 900,
    tema: str = "dark",
    marka: str = "Mimar",
    vurgu_rengi: str = "#F7931A",
    ikincil_renk: str = "#00F0FF",
    ek_not: str = "",
    cikti_adi: str = "",
    ara_dosyalari_sil: bool = True,
) -> str:
    """
    Stok fotoğrafı HTML+CSS post tasarımında kullanır, render eder ve PNG olarak workspace'e kaydeder.

    Fotoğraf kaynağı önceliği:
    1. pexels_photo_id verilirse GET /v1/photos/{id}
    2. stok_fotograf_url verilirse direkt o URL veya yerel dosya
    3. stok_fotograf_query verilirse GET /v1/search
    4. Hiçbiri verilmezse başlık query olarak kullanılır.

    Args:
        baslik: Post ana başlığı.
        alt_baslik: Başlığın altında gösterilecek destek metni.
        cta: Buton/çağrı metni.
        stok_fotograf_query: Pexels fotoğraf arama sorgusu.
        stok_fotograf_url: Hazır stok fotoğraf URL'si veya yerel dosya yolu.
        pexels_photo_id: Kullanılacak Pexels fotoğraf ID'si.
        platform: x, instagram, linkedin gibi çıktı etiketi.
        genislik: PNG genişliği. X için 1600, Instagram kare için 1080 önerilir.
        yukseklik: PNG yüksekliği. X için 900, Instagram kare için 1080 önerilir.
        tema: Şimdilik dark/fintech gibi isimsel metadata.
        marka: Sol üst marka/metin.
        vurgu_rengi: Ana vurgu rengi, HEX.
        ikincil_renk: İkincil vurgu rengi, HEX.
        ek_not: Tasarım altında küçük destek notu.
        cikti_adi: Dosya adı slug'ı. Boşsa başlıktan üretilir.
        ara_dosyalari_sil: True ise PNG render sonrası HTML/CSS/metadata ve geçici görseller silinir.
    """
    try:
        width = _clamp_dimension(genislik, 1600)
        height = _clamp_dimension(yukseklik, 900)
        accent = _normalize_hex(vurgu_rengi, "#F7931A")
        secondary = _normalize_hex(ikincil_renk, "#00F0FF")
        base_slug = _slugify(cikti_adi or baslik or stok_fotograf_query, "post")
        run_slug = f"{base_slug}_{_timestamp()}"
        artifact_dir = _HTML_POSTS_ROOT / run_slug
        assets_dir = artifact_dir / "assets"
        output_dir = _GENERATED_POSTS_ROOT
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        photo_metadata: dict[str, Any] = {}
        image_ref = (stok_fotograf_url or "").strip()
        source_kind = "direct_url" if image_ref else "pexels_search"

        if int(pexels_photo_id or 0) > 0:
            selected_photo = _pexels_get(f"/photos/{int(pexels_photo_id)}")
            photo_metadata = _compact_photo(selected_photo)
            image_ref = _select_photo_url(selected_photo)
            source_kind = "pexels_photo_detail"
        elif image_ref:
            photo_metadata = {
                "id": None,
                "url": image_ref,
                "photographer": "",
                "photographer_url": "",
                "src": {"selected": image_ref},
            }
        else:
            query = (stok_fotograf_query or baslik or "creative social media").strip()
            selected = _pexels_get(
                "/search",
                {
                    "query": query,
                    "orientation": _orientation_for_dimensions(width, height),
                    "per_page": 1,
                    "page": 1,
                },
            )
            photos = selected.get("photos", [])
            if not photos:
                raise RuntimeError(f"Pexels aramasinda sonuc bulunamadi: {query}")
            selected_photo = photos[0]
            photo_metadata = _compact_photo(selected_photo)
            image_ref = _select_photo_url(selected_photo)

        if not image_ref:
            raise RuntimeError("Stok fotoğraf URL'si seçilemedi.")

        local_image = _download_or_copy_image(image_ref, assets_dir)
        image_data_uri = _image_data_uri(local_image)
        document, css = _build_post_html(
            width=width,
            height=height,
            title=baslik,
            subtitle=alt_baslik,
            cta=cta,
            brand=marka,
            note=ek_not,
            platform=platform,
            accent=accent,
            secondary=secondary,
            image_data_uri=image_data_uri,
            photographer=str(photo_metadata.get("photographer") or ""),
            pexels_url=str(photo_metadata.get("url") or ""),
        )

        html_path = artifact_dir / "index.html"
        css_path = artifact_dir / "style.css"
        png_path = output_dir / f"{run_slug}.png"
        metadata_path = artifact_dir / "metadata.json"

        html_path.write_text(document, encoding="utf-8")
        css_path.write_text(css, encoding="utf-8")
        _render_html_to_png(html_path, png_path, width, height)

        metadata = {
            "title": baslik,
            "subtitle": alt_baslik,
            "cta": cta,
            "platform": platform,
            "theme": tema,
            "width": width,
            "height": height,
            "accent": accent,
            "secondary": secondary,
            "source_kind": source_kind,
            "photo": photo_metadata,
            "stock_image_path": str(local_image.resolve()),
            "html_path": str(html_path.resolve()),
            "css_path": str(css_path.resolve()),
            "png_path": str(png_path.resolve()),
            "attribution_required": "Pexels ve fotoğrafçı linkini post metninde veya açıklamada belirt.",
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        intermediate_deleted = False
        deleted_paths: list[str] = []
        if bool(ara_dosyalari_sil):
            deleted_paths = [
                str(html_path.resolve()),
                str(css_path.resolve()),
                str(metadata_path.resolve()),
                str(local_image.resolve()),
            ]
            shutil.rmtree(artifact_dir, ignore_errors=True)
            intermediate_deleted = not artifact_dir.exists()

        return _json_result(
            {
                "status": "ok",
                "message": "HTML+CSS post tasarimi render edilip PNG olarak kaydedildi.",
                "png_path": str(png_path.resolve()),
                "html_path": None if intermediate_deleted else str(html_path.resolve()),
                "css_path": None if intermediate_deleted else str(css_path.resolve()),
                "metadata_path": None if intermediate_deleted else str(metadata_path.resolve()),
                "stock_image_path": None if intermediate_deleted else str(local_image.resolve()),
                "intermediate_files_deleted": intermediate_deleted,
                "deleted_intermediate_paths": deleted_paths if intermediate_deleted else [],
                "dimensions": {"width": width, "height": height},
                "photo": photo_metadata,
                "attribution_required": metadata["attribution_required"],
            }
        )
    except Exception as e:
        return f"❌ HTML/CSS post PNG oluşturma hatası: {e}"

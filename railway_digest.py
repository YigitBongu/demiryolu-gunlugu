#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demiryolu Günlüğü — her sabah otomatik demiryolu bülteni
========================================================
Akış: kaynakları tara -> süz & tekilleştir -> Claude ile Türkçe bülten yaz
      -> web sitesini güncelle (docs/index.html + arşiv) -> (opsiyonel) e-posta gönder.

Ortam değişkenleri (GitHub Secrets olarak tanımlanır):
  GEMINI_API_KEY      (önerilir, ÜCRETSİZ) Google AI Studio anahtarı -> tam Türkçe bülten
  ANTHROPIC_API_KEY   (alternatif, ~1$/ay) Claude ile özet; ikisi de yoksa başlık listesi modu
  GMAIL_ADDRESS       (opsiyonel) Tanımlıysa bülten ayrıca e-postayla da gönderilir
  GMAIL_APP_PASSWORD  (opsiyonel) Gmail "uygulama şifresi" (normal şifren DEĞİL)
  DIGEST_TO           (opsiyonel) Alıcı adres; boşsa GMAIL_ADDRESS kullanılır
"""

import datetime as dt
import hashlib
import html
import json
import os
import re
import smtplib
import ssl
from email.mime.text import MIMEText
from urllib.parse import quote

import feedparser
import requests

# ============================== AYARLAR ==============================

TRT = dt.timezone(dt.timedelta(hours=3))            # Türkiye saati
NOW_UTC = dt.datetime.now(dt.timezone.utc)
NEWS_WINDOW = dt.timedelta(hours=26)                # haberler: son ~1 gün
PAPER_WINDOW = dt.timedelta(days=3)                 # makaleler: son 3 gün
MAX_ITEMS_TO_LLM = 70                               # LLM'e gidecek azami kayıt
CLAUDE_MODEL = "claude-haiku-4-5"                   # (ücretli yol, ~1$/ay) dilersen: claude-sonnet-4-6
GEMINI_MODEL = "gemini-2.5-flash"                   # (ücretsiz yol) Google AI Studio anahtarıyla
SEEN_FILE = "seen.json"                             # mükerrer engelleme durumu
SITE_DIR = "docs"                                   # GitHub Pages kök klasörü
ARCHIVE_DIR = os.path.join(SITE_DIR, "arsiv")       # günlük HTML arşivi


def gnews(q: str, hl: str = "tr-TR", gl: str = "TR", ceid: str = "TR:tr") -> str:
    """Google News RSS arama URL'si üretir (yüzlerce siteyi tek feed'de tarar)."""
    return (f"https://news.google.com/rss/search?q={quote(q)}"
            f"&hl={hl}&gl={gl}&ceid={ceid}")


# (kategori_ipucu, kaynak_adı, feed_url)
# Not: Herhangi bir feed çökerse sessizce atlanır; omurga Google News'tir.
FEEDS = [
    # --- Google News taban sorguları ---
    ("türkiye", "Google News TR",
     gnews('(demiryolu OR "hızlı tren" OR TCDD OR "raylı sistem" OR tramvay OR "metro hattı") when:1d')),
    ("dünya", "Google News EN",
     gnews('(railway OR "high-speed rail" OR "rail infrastructure" OR "rolling stock") when:1d',
           hl="en-US", gl="US", ceid="US:en")),
    ("ihale", "Google News İhale",
     gnews('("demiryolu ihalesi" OR "railway tender" OR "rail contract awarded" OR "metro ihalesi") when:2d',
           hl="en-US", gl="US", ceid="US:en")),
    ("radar", "Google News Radar (frankofon)",
     gnews("(ferroviaire OR \"chemin de fer\") (Afrique OR Sénégal OR Cameroun OR Tanzanie) when:2d",
           hl="fr", gl="FR", ceid="FR:fr")),
    ("radar", "Google News Radar (Yapı Merkezi)",
     gnews('"Yapı Merkezi" OR "Dakar TER" OR "Tanzania SGR" when:3d',
           hl="en-US", gl="US", ceid="US:en")),
    # --- Doğrudan sektör kaynakları ---
    ("dünya", "Railway Gazette", "https://www.railwaygazette.com/149.rss"),
    ("dünya", "Railway Age", "https://www.railwayage.com/feed"),
    ("dünya", "Railway Pro", "https://www.railwaypro.com/wp/feed"),
    ("teknoloji", "RT&S Track & Structures", "https://www.rtands.com/feed"),
    ("türkiye", "RayHaber", "https://rayhaber.com/feed/"),
]

# Bariz alakasız içerik ön filtresi (ince eleme LLM'de yapılır)
BLOCKLIST = re.compile(r"model train|model railway|gravy train", re.IGNORECASE)


# ========================== YARDIMCI FONKSİYONLAR ==========================

def entry_time(entry) -> "dt.datetime | None":
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
    return None


def clean(text: str, limit: int = 280) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit]


def item_key(title: str, link: str) -> str:
    base = re.sub(r"\W+", "", (title or "").lower()) + "|" + (link or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


# ============================ TOPLAYICILAR ============================

def collect_feeds() -> list:
    items = []
    for category, source, url in FEEDS:
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries[:40]:
                ts = entry_time(e)
                if ts and NOW_UTC - ts > NEWS_WINDOW:
                    continue
                title = clean(e.get("title", ""), 200)
                if not title or BLOCKLIST.search(title):
                    continue
                items.append({
                    "kategori": category,
                    "kaynak": source,
                    "baslik": title,
                    "ozet": clean(e.get("summary", "")),
                    "link": e.get("link", ""),
                    "tarih": ts.isoformat() if ts else "",
                })
            print(f"[ok] {source}: {len(parsed.entries)} girdi")
        except Exception as exc:
            print(f"[uyarı] {source} atlandı: {exc}")
    return items


def collect_arxiv() -> list:
    """arXiv: son günlerde yüklenmiş demiryolu ilgili ön baskılar."""
    url = ("https://export.arxiv.org/api/query?"
           "search_query=all:%22railway%22+OR+all:%22high-speed+rail%22+OR+all:%22rail+track%22"
           "&sortBy=submittedDate&sortOrder=descending&max_results=30")
    items = []
    try:
        parsed = feedparser.parse(url)
        for e in parsed.entries:
            ts = entry_time(e)
            if ts and NOW_UTC - ts > PAPER_WINDOW:
                continue
            items.append({
                "kategori": "akademik",
                "kaynak": "arXiv",
                "baslik": clean(e.get("title", ""), 220),
                "ozet": clean(e.get("summary", ""), 320),
                "link": e.get("link", ""),
                "tarih": ts.isoformat() if ts else "",
            })
        print(f"[ok] arXiv: {len(items)} yeni makale")
    except Exception as exc:
        print(f"[uyarı] arXiv atlandı: {exc}")
    return items


def collect_crossref() -> list:
    """Crossref: son günlerde DOI kaydı açılmış hakemli dergi makaleleri."""
    since = (NOW_UTC - PAPER_WINDOW).strftime("%Y-%m-%d")
    mailto = os.environ.get("GMAIL_ADDRESS", "digest@example.com")
    url = ("https://api.crossref.org/works?query=railway"
           f"&filter=from-created-date:{since},type:journal-article"
           "&rows=25&sort=created&order=desc"
           "&select=title,URL,container-title,created")
    items = []
    try:
        r = requests.get(url, timeout=30,
                         headers={"User-Agent": f"DemiryoluGunlugu/1.0 (mailto:{mailto})"})
        r.raise_for_status()
        for w in r.json().get("message", {}).get("items", []):
            title = clean(" ".join(w.get("title") or []), 220)
            if not title:
                continue
            journal = clean(" ".join(w.get("container-title") or []), 90)
            items.append({
                "kategori": "akademik",
                "kaynak": journal or "Crossref",
                "baslik": title,
                "ozet": "",
                "link": w.get("URL", ""),
                "tarih": (w.get("created", {}) or {}).get("date-time", ""),
            })
        print(f"[ok] Crossref: {len(items)} yeni makale")
    except Exception as exc:
        print(f"[uyarı] Crossref atlandı: {exc}")
    return items


# ======================= MÜKERRER ENGELLEME DURUMU =======================

def load_seen() -> list:
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_seen(keys: list) -> None:
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(keys[-4000:], f)


# ========================= CLAUDE İLE ÖZETLEME =========================

PROMPT_SABLONU = """Sen "Demiryolu Günlüğü" adlı günlük sabah bülteninin editörüsün.
Okuyucu: demiryolu sistemleri alanında çalışan bir inşaat/demiryolu mühendisi (Türkiye).
Bugünün tarihi: {tarih}.

Aşağıda son 24-72 saatte çeşitli kaynaklardan toplanmış ham kayıtlar JSON olarak verilmiştir.
Görevin bunlardan TÜRKÇE, taranması kolay bir HTML bülten üretmek.

Kurallar:
1. Aynı gelişmeyi anlatan mükerrer kayıtları tekilleştir; en bilgilendirici olanı seç.
2. Demiryoluyla ilgisiz kayıtları tamamen çıkar (savunma, otomobil, model tren, mecazi kullanımlar vb.).
3. Başlıkları Türkçeye çevir; her madde için 1-2 cümlelik Türkçe özet yaz.
4. Sana verilenler dışında hiçbir bilgi veya haber UYDURMA; linkleri aynen koru.
5. Şu bölümleri bu sırayla üret (bir bölümde madde yoksa tek satır "Bugün öne çıkan gelişme yok." yaz):
   <h2>🔦 Öne Çıkanlar</h2>  (tüm kayıtlar içinden en önemli 4-5 gelişme)
   <h2>🇹🇷 Türkiye</h2>
   <h2>🌍 Dünya</h2>
   <h2>📑 Akademik</h2>
   <h2>📋 İhale &amp; Yatırım</h2>
   <h2>🛰️ Radar: Yapı Merkezi &amp; Frankofon Afrika</h2>
6. Madde biçimi:
   <p><a href="LINK"><b>Türkçe başlık</b></a><br>1-2 cümlelik özet. <i>(Kaynak)</i></p>
7. Toplamda en fazla ~25 madde. Yanıt olarak SADECE HTML gövdesi döndür; markdown, açıklama veya kod bloğu işareti kullanma.

Ham kayıtlar:
{kayitlar}
"""


def build_prompt(items: list) -> str:
    return PROMPT_SABLONU.format(
        tarih=NOW_UTC.astimezone(TRT).strftime("%d.%m.%Y"),
        kayitlar=json.dumps(items[:MAX_ITEMS_TO_LLM], ensure_ascii=False),
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def summarize_with_claude(prompt: str) -> "str | None":
    """Anthropic API ile özetleme (ücretli yol; anahtar yoksa sessizce atlanır)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": CLAUDE_MODEL, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=180,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text")
        return _strip_fences(text) or None
    except Exception as exc:
        print(f"[uyarı] Claude özeti alınamadı: {exc}")
        return None


def summarize_with_gemini(prompt: str) -> "str | None":
    """Google AI Studio'nun ücretsiz katmanıyla özetleme (kredi kartı istemez)."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={key}")
    try:
        r = requests.post(url, timeout=180, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 8000},
        })
        r.raise_for_status()
        cands = r.json().get("candidates", [])
        text = "".join(p.get("text", "")
                       for c in cands[:1]
                       for p in c.get("content", {}).get("parts", []))
        return _strip_fences(text) or None
    except Exception as exc:
        print(f"[uyarı] Gemini özeti alınamadı: {exc}")
        return None


# ========================= YEDEK (HAM) GÖRÜNÜM =========================

BOLUM_ADLARI = [
    ("türkiye", "🇹🇷 Türkiye"),
    ("dünya", "🌍 Dünya"),
    ("akademik", "📑 Akademik"),
    ("ihale", "📋 İhale & Yatırım"),
    ("teknoloji", "🔬 Teknoloji"),
    ("radar", "🛰️ Radar"),
]


def render_fallback(items: list) -> str:
    parts = ["<p><i>Not: Bugün özetleme yapılamadı; ham başlık listesi aşağıdadır.</i></p>"]
    for cat, adi in BOLUM_ADLARI:
        grup = [i for i in items if i["kategori"] == cat]
        if not grup:
            continue
        parts.append(f"<h2>{adi}</h2>")
        for i in grup[:15]:
            parts.append(
                f'<p><a href="{html.escape(i["link"])}"><b>{html.escape(i["baslik"])}</b></a> '
                f'<i>({html.escape(i["kaynak"])})</i></p>'
            )
    return "\n".join(parts)


# ============================ E-POSTA ============================

AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def wrap_page(body_html: str, item_count: int, footer_extra: str = "",
              show_nav: bool = False) -> str:
    """Bülten gövdesini tam HTML sayfasına sarar (site ve e-posta ortak kullanır)."""
    bugun = NOW_UTC.astimezone(TRT)
    tarih = f"{bugun.day} {AYLAR[bugun.month - 1]} {bugun.year}"
    # Üst navigasyon yalnızca web sitesinde gösterilir (e-postada değil)
    nav = ('<p style="font-size:14px;margin:0 0 16px"><a href="index.html">Bugün</a> '
           '&middot; <a href="arsiv.html">🗂️ Tüm Arşiv</a></p>') if show_nav else ""
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🚆 Demiryolu Günlüğü — {tarih}</title></head>
<body style="font-family:Georgia,'Times New Roman',serif;max-width:680px;margin:auto;padding:12px;color:#222;line-height:1.55">
<h1 style="border-bottom:3px solid #1a5276;padding-bottom:8px;margin-bottom:4px">🚆 Demiryolu Günlüğü</h1>
<p style="color:#777;margin-top:0">{tarih} &middot; {item_count} yeni kayıt tarandı</p>
{nav}
{body_html}
<hr style="border:none;border-top:1px solid #ddd;margin-top:24px">
{footer_extra}
<p style="font-size:12px;color:#999">Bu bülten GitHub Actions üzerinde otomatik üretilmiştir.</p>
</body></html>"""


def render_archive_page() -> str:
    """Tüm arşivlenmiş günleri tarihe göre listeleyen ayrı bir sayfa üretir."""
    try:
        files = sorted((f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".html")),
                       reverse=True)
    except FileNotFoundError:
        files = []
    if files:
        satirlar = "\n".join(
            f'<li style="margin:6px 0"><a href="arsiv/{f}">{f[:-5]}</a></li>'
            for f in files)
        liste = f'<ul style="list-style:none;padding:0;font-size:16px">{satirlar}</ul>'
    else:
        liste = "<p>Henüz arşivlenmiş bülten yok.</p>"
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🗂️ Demiryolu Günlüğü — Arşiv</title></head>
<body style="font-family:Georgia,'Times New Roman',serif;max-width:680px;margin:auto;padding:12px;color:#222;line-height:1.55">
<h1 style="border-bottom:3px solid #1a5276;padding-bottom:8px">🗂️ Arşiv</h1>
<p style="font-size:14px"><a href="index.html">← Bugünün bültenine dön</a></p>
<p style="color:#777">Geçmiş günlerin bültenleri (en yeni üstte):</p>
{liste}
</body></html>"""


def archive_links_html() -> str:
    """Site alt bilgisi için son 30 günün arşiv linklerini üretir."""
    try:
        files = sorted(f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".html"))[-30:]
    except FileNotFoundError:
        return ""
    if not files:
        return ""
    links = " &middot; ".join(f'<a href="arsiv/{f}">{f[:-5]}</a>' for f in reversed(files))
    return f'<p style="font-size:13px;color:#777"><b>Arşiv:</b> {links}</p>'


def send_email(full_html: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("DIGEST_TO", "").strip() or sender
    bugun = NOW_UTC.astimezone(TRT)
    tarih = f"{bugun.day} {AYLAR[bugun.month - 1]} {bugun.year}"

    msg = MIMEText(full_html, "html", "utf-8")
    msg["Subject"] = f"🚆 Demiryolu Günlüğü — {tarih}"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                          context=ssl.create_default_context()) as s:
        s.login(sender, password)
        s.sendmail(sender, [recipient], msg.as_string())


# ============================== ANA AKIŞ ==============================

def main() -> None:
    items = collect_feeds() + collect_arxiv() + collect_crossref()
    print(f"Toplanan ham kayıt: {len(items)}")

    seen_list = load_seen()
    seen_set = set(seen_list)
    fresh, new_keys = [], []
    for it in items:
        k = item_key(it["baslik"], it["link"])
        if k in seen_set:
            continue
        seen_set.add(k)
        new_keys.append(k)
        fresh.append(it)
    print(f"Yeni (daha önce gönderilmemiş): {len(fresh)}")

    if not fresh:
        print("Yeni kayıt yok; bugün bülten üretilmiyor.")
        return

    fresh.sort(key=lambda i: i.get("tarih", ""), reverse=True)
    prompt = build_prompt(fresh)
    body = (summarize_with_gemini(prompt)      # 1. tercih: ücretsiz (Google AI Studio)
            or summarize_with_claude(prompt)   # 2. tercih: ücretli Claude (varsa)
            or render_fallback(fresh))         # 3. yedek: ham başlık listesi
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        print("[bilgi] Özet anahtarı yok; ham başlık listesi üretildi.")

    # 1) WEB SİTESİ — her koşulda güncellenir (docs/ -> GitHub Pages)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    open(os.path.join(SITE_DIR, ".nojekyll"), "w").close()
    tarih_dosya = NOW_UTC.astimezone(TRT).strftime("%Y-%m-%d")
    # Önce bugünün arşiv kopyasını yaz (arşiv sayfası ve alt-bilgi bunu görsün)
    with open(os.path.join(ARCHIVE_DIR, tarih_dosya + ".html"), "w", encoding="utf-8") as f:
        f.write(wrap_page(body, len(fresh), show_nav=True))
    # Ana sayfa: üstte navigasyon + altta son 30 günün hızlı linkleri
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(wrap_page(body, len(fresh),
                          footer_extra=archive_links_html(), show_nav=True))
    # Ayrı, tam arşiv sayfası (tüm günler)
    with open(os.path.join(SITE_DIR, "arsiv.html"), "w", encoding="utf-8") as f:
        f.write(render_archive_page())
    print(f"Site güncellendi: index.html + arsiv.html (+ arşiv: {tarih_dosya}.html)")

    # 2) E-POSTA — opsiyonel: Gmail secret'ları tanımlıysa gönderilir
    if os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"):
        send_email(wrap_page(body, len(fresh)))
        print("E-posta gönderildi.")
    else:
        print("[bilgi] Gmail secret'ları tanımlı değil; e-posta atlandı (site yine de güncel).")

    save_seen(seen_list + new_keys)


if __name__ == "__main__":
    main()

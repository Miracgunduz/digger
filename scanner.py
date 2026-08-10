"""
Firsat Avcisi - ortak cekirdek mantik.

Reddit veri toplama, Gemini analizi ve Telegram bildirimi burada tanimli.
Bu modul tek basina calismaz; notify.py (zamanlanmis bildirim) ve
run_command.py (workflow_dispatch ile tetiklenen komutlar) tarafindan import edilir.
"""

import html
import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests
from dotenv import load_dotenv

# --------------------------------------------------------------------------
# YAPILANDIRMA - API key'leri ve ayarlar burada, en ustte
# --------------------------------------------------------------------------

load_dotenv()  # Ayni klasordeki ".env" dosyasini varsa yukler

# NOT: Reddit'in resmi Data API'si (PRAW/OAuth) su an onay bekliyor
# (bkz. Reddit'e gonderilen Data Access Request ticket'i). Onaylanana kadar
# asagidaki RSS tabanli, anahtarsiz yontem kullaniliyor. Onay gelince
# REDDIT_CLIENT_ID/SECRET burada tekrar aktif edilip fetch_reddit_data PRAW'a
# cevrilebilir - mimari buna gore modduler tutuldu.
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "firsat-avcisi-bot/1.0")

# Yapay zeka analizi Google Gemini API'sinin ucretsiz katmaniyla yapiliyor
# (kredi karti gerektirmiyor, gunluk 1500 istek limiti bu proje icin fazlasiyla yeterli).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SUBREDDITS = [
    "ClaudeAI",
    "vibecoding",
    "passive_income",
    "SideProject",
    "Entrepreneur",
    "startups",
    "marketing",
    "micro_saas",
    "founder",
    "apps",
]

COMMENTS_PER_POST = 3          # Her gonderiden alinacak en cok oy alan yorum sayisi
TELEGRAM_CHUNK_LIMIT = 3800    # Telegram 4096 karakter siniri var, guvenli pay birakiyoruz

# Reddit'in anonim (girissiz) RSS erisiminde istek basina ~50 sn rate-limit
# reset suresi gozlemlendi (x-ratelimit-reset header'i). Her istek arasinda
# bu kadar bekleyerek 429 hatalarindan kaciniyoruz.
RSS_REQUEST_DELAY_SECONDS = 55
RSS_MAX_RETRIES = 2
ATOM_NS = "{http://www.w3.org/2005/Atom}"

DAILY_BULLETIN_SYSTEM_PROMPT = """Sen, bağımsız geliştiriciler (solopreneur) için kârlı, düşük maliyetli ve hayata geçirilmesi pratik yan gelir (side-hustle) ve Micro-SaaS projeleri bulma konusunda uzmanlaşmış kıdemli bir ürün stratejistisin.
GÖREVİN: Sana sunulan Reddit verilerini analiz edip benim için yüksek potansiyelli bir 'Günlük Fırsat Bülteni' hazırlaman.
KURALLAR:
- Büyük ekip, yüksek donanım veya devasa sunucu altyapısı gerektiren fikirleri KESİNLİKLE ELE.
- Sadece tek bir yazılımcının sıfır sermaye ile 1-2 ayda MVP yapabileceği EN İYİ 3 fikri seç.
- Orijinal fikri sadece özetleme, projeyi çok daha kârlı veya çekici yapacak bir 'Ekstra İnovasyon' ekle.
- Seçtiğin her fikir için piyasadaki rakipleri ve pazardaki boşluğu da analiz et.
- Fikirlerin teknik zorluk derecesini belirlerken, Python, .NET, CSS ve SQL dillerine aşina olan bir geliştiricinin profiline göre 1 ile 10 arasında bir puan ver. Puanı şu emojilerle işaretle: 🟢 (1-3, kolay) / 🟠 (4-7, orta) / 🔴 (8-10, zor).
ÇIKTI FORMATI:
SADECE aşağıdaki JSON formatında çıktı ver. JSON bloğu dışında selamlama veya açıklama yazma:
{
  "gunluk_bulten": [
    {
      "baslik": "Fikrin vurucu adı",
      "kaynak_subreddit": "r/isim",
      "orijinal_fikir_ozeti": "Gönderinin ve problemin özeti",
      "neden_mantikli_ve_uygun": "Neden bütçesiz yapılmaya uygun?",
      "teknik_zorluk_puani": "Örn: 🟠 6/10 (Sadece sayı ve uygun renkli emoji)",
      "gereken_teknolojiler": "Projenin yapılması için gereken temel diller ve frameworkler (Örn: Python, FastAPI, React)",
      "ekstra_inovasyon": "Projeyi 10x yapacak senin eklentin",
      "rakip_analizi_ve_acik_kapi": "Piyasadaki mevcut büyük veya benzer rakipler kimler? Onların zayıf yönleri (pahalı, karmaşık, kötü destek vb.) neler? Ben hangi nişe/boşluğa odaklanarak pazardan pay çalabilirim?",
      "hedef_kitle_ve_monetizasyon": "Kim kullanır, nasıl para kazanılır?"
    }
  ]
}"""

COMPETITOR_SYSTEM_PROMPT = """Sen uzman bir pazar araştırmacısısın. Kullanıcının verdiği ürün fikri için piyasadaki mevcut popüler rakipleri listele, onların zayıf/eksik yönlerini analiz et ve tek bir indie geliştiricinin onlardan nasıl pazar payı çalabileceğini (fırsat boşluğunu) net bir şekilde açıkla.

Cevabini Telegram'da guzel gorunecek sade Markdown ile ver (kalin baslik/ifadeler icin *yildiz*, madde isaretleri icin '-', kod bloğu veya '#' baslik kullanma)."""

COST_SYSTEM_PROMPT = """Sen kıdemli bir Cloud Mimarı ve Finansal Analistsin. Kullanıcının verdiği proje fikri için ilk 6 aylık tahmini sunucu (AWS, Vercel vb.), veritabanı ve dış API (OpenAI, Stripe vb.) masraflarını çıkar. Projenin zarar etmemesi için kullanıcıdan alınması gereken minimum aylık abonelik ücretini hesapla ve bunu detaylı bir fatura dökümü gibi Markdown formatında sun.

Cevabini Telegram'da guzel gorunecek sade Markdown ile ver (kalin baslik/ifadeler icin *yildiz*, madde isaretleri icin '-', kod bloğu veya '#' baslik kullanma)."""

PAIN_POINT_SYSTEM_PROMPT = """Sen bir ürün stratejistisin. Sana verilen bu şikayet dolu Reddit verilerini analiz et. İnsanların en çok kanayan, çözülmeyi bekleyen 3 yarasını (pain point) bul. Her bir şikayet için, tek bir yazılımcının sıfır sermaye ile yapabileceği basit, kârlı bir Micro-SaaS çözüm önerisi sun.

Cevabini Telegram'da guzel gorunecek sade Markdown ile ver (kalin baslik/ifadeler icin *yildiz*, madde isaretleri icin '-', kod bloğu veya '#' baslik kullanma)."""

# Reddit arama sorgusu: sikayet/talep belirten kaliplari yakalar (search.rss ile kullanilir)
PAIN_POINT_SEARCH_QUERY = '"I hate" OR "struggling with" OR "is there a tool for" OR "alternative to" OR "tired of"'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("firsat_avcisi")


# --------------------------------------------------------------------------
# 1. VERI TOPLAMA (Reddit RSS - anahtarsiz, OAuth onayi beklerken kullanilan gecici yontem)
# --------------------------------------------------------------------------

def _strip_reddit_rss_html(raw_html):
    """RSS icerigindeki HTML etiketlerini ve Reddit'in otomatik ekledigi
    'submitted by ... [link] [comments]' kuyrugunu temizler."""
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    text = re.split(r"submitted by", text, flags=re.IGNORECASE)[0]
    return re.sub(r"\s+", " ", text).strip()


def _fetch_rss(url, params=None):
    """Verilen Reddit RSS URL'sini ceker, 429 durumunda Retry-After'a gore bekleyip tekrar dener."""
    headers = {"User-Agent": REDDIT_USER_AGENT}

    for attempt in range(RSS_MAX_RETRIES + 1):
        resp = requests.get(url, headers=headers, params=params, timeout=20)

        if resp.status_code == 200:
            return ET.fromstring(resp.content)

        if resp.status_code == 429 and attempt < RSS_MAX_RETRIES:
            wait_seconds = int(resp.headers.get("x-ratelimit-reset", RSS_REQUEST_DELAY_SECONDS))
            logger.warning("Reddit rate limit (429), %d sn beklenip tekrar denenecek.", wait_seconds)
            time.sleep(wait_seconds + 2)
            continue

        resp.raise_for_status()

    raise RuntimeError(f"RSS istegi basarisiz oldu: {url}")


def fetch_reddit_data(subreddits):
    """Verilen subredditlerin son 24 saatteki en iyi (top) gonderisini ve
    o gonderinin en cok oy alan ilk N yorumunu Reddit'in genel RSS
    uc noktalarindan (anahtarsiz) ceker. Anonim erisimde istek basina
    siki rate-limit oldugundan istekler arasina bilincli gecikme konur."""
    collected = []

    for index, sub_name in enumerate(subreddits):
        try:
            if index > 0:
                time.sleep(RSS_REQUEST_DELAY_SECONDS)

            list_url = f"https://www.reddit.com/r/{sub_name}/top/.rss?t=day&limit=1"
            feed_root = _fetch_rss(list_url)
            entries = feed_root.findall(f"{ATOM_NS}entry")

            if not entries:
                logger.info("r/%s: son 24 saatte gonderi bulunamadi.", sub_name)
                continue

            entry = entries[0]
            post_title = (entry.findtext(f"{ATOM_NS}title") or "").strip()
            post_body = _strip_reddit_rss_html(entry.findtext(f"{ATOM_NS}content"))[:1500]
            link_el = entry.find(f"{ATOM_NS}link")
            post_link = link_el.get("href") if link_el is not None else ""

            comment_texts = []
            if post_link:
                time.sleep(RSS_REQUEST_DELAY_SECONDS)
                comments_url = f"{post_link.rstrip('/')}.rss?sort=top&limit={COMMENTS_PER_POST + 1}"
                try:
                    comments_root = _fetch_rss(comments_url)
                    comment_entries = comments_root.findall(f"{ATOM_NS}entry")[1:1 + COMMENTS_PER_POST]
                    for c_entry in comment_entries:
                        c_text = _strip_reddit_rss_html(c_entry.findtext(f"{ATOM_NS}content"))
                        if c_text:
                            comment_texts.append(c_text[:800])
                except Exception as comment_err:
                    logger.warning("Yorumlar cekilemedi (r/%s): %s", sub_name, comment_err)

            collected.append({
                "subreddit": f"r/{sub_name}",
                "baslik": post_title,
                "gonderi_metni": post_body,
                "url": post_link,
                "en_iyi_yorumlar": comment_texts,
            })
            logger.info("r/%s tarandi.", sub_name)

        except Exception as sub_err:
            logger.error("r/%s taranirken hata olustu: %s", sub_name, sub_err)
            continue

    return collected


def fetch_reddit_pain_points(subreddits):
    """Verilen subredditlerde son 1 haftada, sikayet/talep belirten kaliplara
    (PAIN_POINT_SEARCH_QUERY) uyan en iyi gonderiyi ve yorumlarini
    Reddit'in arama RSS uc noktasindan (anahtarsiz) ceker."""
    collected = []

    for index, sub_name in enumerate(subreddits):
        try:
            if index > 0:
                time.sleep(RSS_REQUEST_DELAY_SECONDS)

            search_url = f"https://www.reddit.com/r/{sub_name}/search.rss"
            feed_root = _fetch_rss(search_url, params={
                "q": PAIN_POINT_SEARCH_QUERY,
                "restrict_sr": "on",
                "sort": "top",
                "t": "week",
                "limit": 1,
            })
            entries = feed_root.findall(f"{ATOM_NS}entry")

            if not entries:
                logger.info("r/%s: sikayet kriterine uyan gonderi bulunamadi.", sub_name)
                continue

            entry = entries[0]
            post_title = (entry.findtext(f"{ATOM_NS}title") or "").strip()
            post_body = _strip_reddit_rss_html(entry.findtext(f"{ATOM_NS}content"))[:1500]
            link_el = entry.find(f"{ATOM_NS}link")
            post_link = link_el.get("href") if link_el is not None else ""

            comment_texts = []
            if post_link:
                time.sleep(RSS_REQUEST_DELAY_SECONDS)
                comments_url = f"{post_link.rstrip('/')}.rss?sort=top&limit={COMMENTS_PER_POST + 1}"
                try:
                    comments_root = _fetch_rss(comments_url)
                    comment_entries = comments_root.findall(f"{ATOM_NS}entry")[1:1 + COMMENTS_PER_POST]
                    for c_entry in comment_entries:
                        c_text = _strip_reddit_rss_html(c_entry.findtext(f"{ATOM_NS}content"))
                        if c_text:
                            comment_texts.append(c_text[:800])
                except Exception as comment_err:
                    logger.warning("Yorumlar cekilemedi (r/%s): %s", sub_name, comment_err)

            collected.append({
                "subreddit": f"r/{sub_name}",
                "baslik": post_title,
                "gonderi_metni": post_body,
                "url": post_link,
                "en_iyi_yorumlar": comment_texts,
            })
            logger.info("r/%s (sikayet taramasi) tarandi.", sub_name)

        except Exception as sub_err:
            logger.error("r/%s sikayet taramasi sirasinda hata olustu: %s", sub_name, sub_err)
            continue

    return collected


# --------------------------------------------------------------------------
# 2. YAPAY ZEKA ANALIZI (Google Gemini API - ucretsiz katman)
# --------------------------------------------------------------------------

def _call_gemini(system_prompt, user_message, json_mode=False, max_output_tokens=4096, temperature=0.7):
    """Gemini generateContent uc noktasina istek atar, uretilen ham metni dondurur."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    generation_config = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if json_mode:
        generation_config["response_mime_type"] = "application/json"

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": generation_config,
    }

    resp = requests.post(
        url,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError(f"Gemini yanitinda aday (candidate) yok. Ham yanit: {json.dumps(data)[:500]}")

    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def analyze_with_gemini(reddit_data):
    """Ham Reddit verisini Gemini API'sine gonderip yapilandirilmis
    JSON bulten olarak geri alir."""
    if not reddit_data:
        raise ValueError("Analiz edilecek Reddit verisi bos.")

    user_message = (
        "Asagida son 24 saatte toplanan Reddit gonderileri ve yorumlari JSON formatinda "
        "verilmistir. Bu veriyi sistem talimatlarina gore analiz et:\n\n"
        + json.dumps(reddit_data, ensure_ascii=False, indent=2)
    )

    # max_output_tokens yukseltildi: rakip_analizi_ve_acik_kapi alani eklendikten
    # sonra 3 fikirlik JSON bazen 4096 token sinirinda kesilip parse hatasi
    # veriyordu (bkz. 2026-08-10 sabah calismasinin hatasi).
    raw_text = _call_gemini(DAILY_BULLETIN_SYSTEM_PROMPT, user_message, json_mode=True, max_output_tokens=8192)
    return parse_ai_json(raw_text)


def research_competitors(idea_text):
    """/rakipbul komutu icin: verilen fikir/proje metnini Gemini'ye gonderip
    rakip analizi ve pazar bosluğu hakkinda serbest metin (Markdown) alir."""
    if not idea_text or not idea_text.strip():
        raise ValueError("Analiz edilecek fikir metni bos.")

    user_message = f"Kullanicinin urun/proje fikri:\n\n{idea_text.strip()}"
    raw_text = _call_gemini(COMPETITOR_SYSTEM_PROMPT, user_message, json_mode=False, max_output_tokens=2048)
    return raw_text.strip()


def analyze_cost(idea_text):
    """/maliyet komutu icin: verilen fikir/proje metnini Gemini'ye gonderip
    ilk 6 ayin tahmini altyapi maliyeti ve minimum abonelik fiyati hakkinda
    serbest metin (Markdown) alir."""
    if not idea_text or not idea_text.strip():
        raise ValueError("Analiz edilecek fikir metni bos.")

    user_message = f"Kullanicinin urun/proje fikri:\n\n{idea_text.strip()}"
    raw_text = _call_gemini(COST_SYSTEM_PROMPT, user_message, json_mode=False, max_output_tokens=2048)
    return raw_text.strip()


def analyze_pain_points(pain_data):
    """/trendler komutu icin: sikayet dolu Reddit verisini Gemini'ye gonderip
    en acil 3 pain point ve Micro-SaaS cozüm onerilerini serbest metin (Markdown) olarak alir."""
    if not pain_data:
        raise ValueError("Analiz edilecek sikayet verisi bos.")

    user_message = (
        "Asagida son 1 haftada toplanan, sikayet/problem iceren Reddit gonderileri ve "
        "yorumlari JSON formatinda verilmistir. Bu veriyi sistem talimatlarina gore analiz et:\n\n"
        + json.dumps(pain_data, ensure_ascii=False, indent=2)
    )

    raw_text = _call_gemini(PAIN_POINT_SYSTEM_PROMPT, user_message, json_mode=False, max_output_tokens=3000)
    return raw_text.strip()


def parse_ai_json(raw_text):
    """Modelin dondurdugu metni JSON'a cevirir. Model bazen JSON'u
    ```json ... ``` bloguna sarabiliyor, buna karsi da onlem alir."""
    cleaned = raw_text.strip()

    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Model yaniti JSON'a cevrilemedi: {exc}\nHam yanit: {raw_text[:500]}")
        raise ValueError(f"Model yanitinda JSON bulunamadi. Ham yanit: {raw_text[:500]}")


# --------------------------------------------------------------------------
# 3. BILDIRIM (Telegram API)
# --------------------------------------------------------------------------

def format_telegram_message(bulten_json):
    """Gemini'den gelen JSON'u sik, emojili bir Markdown mesajina cevirir."""
    fikirler = bulten_json.get("gunluk_bulten", [])
    if not fikirler:
        return ["🔍 *Fırsat Avcısı*\n\nBugün kriterlere uyan bir fırsat bulunamadı."]

    tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
    header = f"🎯 *Fırsat Avcısı - Bülten*\n📅 {tarih}\n"

    parts = [header]
    for i, fikir in enumerate(fikirler, start=1):
        parts.append(
            f"\n\n*{i}. {fikir.get('baslik', 'Basliksiz Fikir')}*\n"
            f"📍 Kaynak: {fikir.get('kaynak_subreddit', '-')}\n\n"
            f"📝 *Özet:* {fikir.get('orijinal_fikir_ozeti', '-')}\n\n"
            f"✅ *Neden Uygun:* {fikir.get('neden_mantikli_ve_uygun', '-')}\n\n"
            f"🛠️ *Teknik Zorluk:* {fikir.get('teknik_zorluk_puani', '-')}\n"
            f"🧰 *Gereken Teknolojiler:* {fikir.get('gereken_teknolojiler', '-')}\n\n"
            f"💡 *Ekstra İnovasyon:* {fikir.get('ekstra_inovasyon', '-')}\n\n"
            f"🥊 *Rakip Analizi & Açık Kapı:* {fikir.get('rakip_analizi_ve_acik_kapi', '-')}\n\n"
            f"💰 *Hedef Kitle & Monetizasyon:* {fikir.get('hedef_kitle_ve_monetizasyon', '-')}"
        )

    full_text = "".join(parts)

    # Telegram mesaj uzunlugu sinirina karsi parcalama
    if len(full_text) <= TELEGRAM_CHUNK_LIMIT:
        return [full_text]

    chunks = []
    current = ""
    for part in parts:
        if len(current) + len(part) > TELEGRAM_CHUNK_LIMIT:
            chunks.append(current)
            current = part
        else:
            current += part
    if current:
        chunks.append(current)
    return chunks


def chunk_text(text, limit=TELEGRAM_CHUNK_LIMIT):
    """Serbest bicimli (Markdown) bir metni Telegram mesaj limitine gore
    paragraf sinirlarindan bolmeye calisan genel amacli parcalayici.
    /rakipbul ve /trendler gibi JSON'a bagli olmayan ciktilar icin kullanilir."""
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        piece = paragraph + "\n\n"
        if len(piece) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for i in range(0, len(piece), limit):
                chunks.append(piece[i:i + limit])
            continue
        if len(current) + len(piece) > limit:
            chunks.append(current.rstrip())
            current = piece
        else:
            current += piece
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def send_telegram_message(chunks, chat_id=None):
    """Hazirlanan Markdown mesaj(lar)ini Telegram Bot API ile gonderir."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    target_chat_id = chat_id or TELEGRAM_CHAT_ID

    for chunk in chunks:
        payload = {
            "chat_id": target_chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Telegram mesaji gonderilemedi: %s", exc)
            raise


# --------------------------------------------------------------------------
# ORTAK TARAMA AKISI
# --------------------------------------------------------------------------

def validate_config():
    required = {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise EnvironmentError(f"Eksik ortam degiskenleri: {', '.join(missing)}")


def run_scan_and_notify(trigger_source="cron", chat_id=None):
    """Tam tarama akisini (Reddit -> Gemini -> Telegram) calistirir.

    trigger_source: loglarda ayirt etmek icin ("scheduled" / "manual").
    chat_id: belirtilmezse TELEGRAM_CHAT_ID kullanilir (komut gonderen
    kisi farkli bir chat'ten yaziyorsa oraya cevap vermek icin kullanilir).
    """
    validate_config()
    logger.info("Tarama basladi (kaynak: %s).", trigger_source)

    reddit_data = fetch_reddit_data(SUBREDDITS)
    logger.info("%d gonderi toplandi.", len(reddit_data))

    if not reddit_data:
        send_telegram_message(
            ["🔍 *Fırsat Avcısı*\n\nSon 24 saatte kriterlere uyan gönderi bulunamadı."],
            chat_id=chat_id,
        )
        logger.info("Uygun gonderi yok, bilgilendirme mesaji gonderildi.")
        return

    bulten_json = analyze_with_gemini(reddit_data)
    logger.info("Gemini analizi tamamlandi, %d fikir uretildi.",
                len(bulten_json.get("gunluk_bulten", [])))

    chunks = format_telegram_message(bulten_json)
    send_telegram_message(chunks, chat_id=chat_id)
    logger.info("Tarama tamamlandi (kaynak: %s).", trigger_source)

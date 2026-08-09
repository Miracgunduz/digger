"""
Firsat Avcisi - komut dinleyici girisi.

Sonsuz donguye GIRMEZ. Cron ile her dakika (* * * * *) tetiklenir;
her calistiginda Telegram'a kisa sureli (long-poll) bir istek atip
bekleyen komut var mi diye bakar, varsa isler, sonra surec kapanir.
Boylece "herhangi bir saatte" komutla tarama hissi verirken cron
disinda hicbir surekli process calismaz.

Desteklenen komutlar:
  /tara, /scan -> anlik tarama baslatir
  /rakipbul <fikir> -> verilen fikir icin rakip/pazar bosluğu analizi yapar
  /trendler -> son 1 haftanin sikayet/firsat taramasini yapar
  /start, /help -> kisa yardim mesaji gonderir
"""

import os
import sys
import time

import requests

from scanner import (
    SUBREDDITS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    analyze_pain_points,
    chunk_text,
    fetch_reddit_pain_points,
    logger,
    research_competitors,
    run_scan_and_notify,
    send_telegram_message,
    validate_config,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "state")
OFFSET_FILE = os.path.join(STATE_DIR, "last_update_id.txt")
LOCK_FILE = os.path.join(STATE_DIR, "listener.lock")

LONG_POLL_TIMEOUT = 25    # saniye - Telegram'a acik kalan istek suresi
# Reddit RSS rate-limit'i nedeniyle bir tarama ~15-20 dakika surebiliyor;
# kilit bu sureden acikca uzun olmali ki calisan taramanin ortasinda
# "askida kalmis" sanilip silinmesin.
LOCK_STALE_SECONDS = 1800  # 30 dakika

SCAN_COMMANDS = {"/tara", "/scan"}
COMPETITOR_COMMANDS = {"/rakipbul"}
TREND_COMMANDS = {"/trendler"}
HELP_COMMANDS = {"/start", "/help"}

HELP_TEXT = (
    "🤖 *Fırsat Avcısı Bot*\n\n"
    "Kullanılabilir komutlar:\n"
    "/tara veya /scan — şimdi anlık tarama başlat\n"
    "/rakipbul <fikir> — verilen fikir için rakip ve pazar boşluğu analizi yap\n"
    "  örnek: /rakipbul Notion benzeri sade not alma uygulaması\n"
    "/trendler — son 1 haftanın şikayet/fırsat taramasını yap\n"
    "/help — bu mesajı göster\n\n"
    "Otomatik bültenler her gün 09:00 ve 21:00'de kendiliğinden gönderilir."
)


def acquire_lock():
    """Ayni anda birden fazla listen.py calismasin diye dosya tabanli kilit."""
    os.makedirs(STATE_DIR, exist_ok=True)

    if os.path.exists(LOCK_FILE):
        age = time.time() - os.path.getmtime(LOCK_FILE)
        if age > LOCK_STALE_SECONDS:
            logger.warning("Eski/askida kalmis kilit dosyasi temizleniyor (yas: %.0f sn).", age)
            os.remove(LOCK_FILE)
        else:
            return False

    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock():
    try:
        os.remove(LOCK_FILE)
    except FileNotFoundError:
        pass


def read_offset():
    if not os.path.exists(OFFSET_FILE):
        return 0
    try:
        with open(OFFSET_FILE, "r") as f:
            return int(f.read().strip() or 0)
    except (ValueError, OSError):
        return 0


def write_offset(update_id):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(OFFSET_FILE, "w") as f:
        f.write(str(update_id))


def get_updates(offset):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": LONG_POLL_TIMEOUT}
    resp = requests.get(url, params=params, timeout=LONG_POLL_TIMEOUT + 10)
    resp.raise_for_status()
    return resp.json().get("result", [])


def parse_command(text):
    """'/rakipbul@BotAdi fikir metni' gibi metni (komut, argüman) ikilisine ayirir.
    Bot etiketini (@BotAdi) temizler, komutu kucuk harfe cevirir."""
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@")[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument


def handle_scan(chat_id):
    logger.info("Manuel tarama komutu alindi.")
    send_telegram_message(
        ["⏳ Tarama başlatıldı. Reddit'in ücretsiz erişim hız sınırı nedeniyle ~15-20 dakika sürebilir, bitince buraya bildirim gelecek."],
        chat_id=chat_id,
    )
    try:
        run_scan_and_notify(trigger_source="manual", chat_id=chat_id)
    except Exception as exc:
        logger.error("Manuel tarama basarisiz: %s", exc)
        send_telegram_message([f"❌ Tarama sırasında hata oluştu: {exc}"], chat_id=chat_id)


def handle_rakipbul(argument, chat_id):
    if not argument:
        send_telegram_message(
            ["⚠️ Kullanım: /rakipbul <fikir veya proje adı>\nÖrnek: /rakipbul Notion benzeri sade not alma uygulaması"],
            chat_id=chat_id,
        )
        return

    logger.info("Rakip analizi komutu alindi: %s", argument[:80])
    send_telegram_message(["🔍 Rakip analizi yapılıyor, birazdan sonuç gelecek..."], chat_id=chat_id)
    try:
        result_text = research_competitors(argument)
        message = f"🥊 *Rakip Analizi: {argument}*\n\n{result_text}"
        send_telegram_message(chunk_text(message), chat_id=chat_id)
        logger.info("Rakip analizi tamamlandi.")
    except Exception as exc:
        logger.error("Rakip analizi basarisiz: %s", exc)
        send_telegram_message([f"❌ Rakip analizi sırasında hata oluştu: {exc}"], chat_id=chat_id)


def handle_trendler(chat_id):
    logger.info("Trend/sikayet taramasi komutu alindi.")
    send_telegram_message(
        ["⏳ Haftalık şikayet/fırsat taraması başlatıldı. Reddit'in ücretsiz erişim hız sınırı nedeniyle ~15-20 dakika sürebilir."],
        chat_id=chat_id,
    )
    try:
        pain_data = fetch_reddit_pain_points(SUBREDDITS)
        if not pain_data:
            send_telegram_message(
                ["🚨 *Haftanın Acı Noktaları ve Fırsatlar*\n\nBu hafta kriterlere uyan şikayet gönderisi bulunamadı."],
                chat_id=chat_id,
            )
            logger.info("Sikayet kriterine uyan gonderi bulunamadi.")
            return

        result_text = analyze_pain_points(pain_data)
        message = f"🚨 *Haftanın Acı Noktaları ve Fırsatlar*\n\n{result_text}"
        send_telegram_message(chunk_text(message), chat_id=chat_id)
        logger.info("Trend/sikayet taramasi tamamlandi.")
    except Exception as exc:
        logger.error("Trend taramasi basarisiz: %s", exc)
        send_telegram_message([f"❌ Trend taraması sırasında hata oluştu: {exc}"], chat_id=chat_id)


def handle_update(update):
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "")

    if chat_id != str(TELEGRAM_CHAT_ID):
        logger.warning("Yetkisiz chat'ten mesaj alindi, yoksayiliyor: %s", chat_id)
        return

    if not text.startswith("/"):
        return

    command, argument = parse_command(text)

    if command in SCAN_COMMANDS:
        handle_scan(chat_id)

    elif command in COMPETITOR_COMMANDS:
        handle_rakipbul(argument, chat_id)

    elif command in TREND_COMMANDS:
        handle_trendler(chat_id)

    elif command in HELP_COMMANDS:
        send_telegram_message([HELP_TEXT], chat_id=chat_id)

    else:
        logger.info("Bilinmeyen komut alindi: %s", command)


def main():
    try:
        validate_config()
    except EnvironmentError as exc:
        logger.critical(exc)
        sys.exit(1)

    if not acquire_lock():
        logger.info("Baska bir listen.py calisiyor, bu calisma atlaniyor.")
        sys.exit(0)

    try:
        offset = read_offset()
        try:
            updates = get_updates(offset)
        except requests.RequestException as exc:
            logger.error("Telegram getUpdates basarisiz: %s", exc)
            sys.exit(1)

        for update in updates:
            handle_update(update)
            write_offset(update["update_id"] + 1)

    finally:
        release_lock()


if __name__ == "__main__":
    main()

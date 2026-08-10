"""
Firsat Avcisi - workflow_dispatch ile tetiklenen komut yurutucusu.

Sonsuz donguye veya polling'e GIRMEZ. Cloudflare Worker (worker/telegram-webhook.js)
Telegram'dan gelen mesaji aninda karsilar ve GitHub Actions'ta bu script'i
COMMAND/ARGUMENT ortam degiskenleriyle tetikler (workflow_dispatch inputs).
Script bir komutu calistirip kapanir.

Desteklenen komutlar (DISPATCH_COMMAND ortam degiskeni):
  tara       -> gunluk tarama + Telegram bulteni
  trendler   -> haftalik sikayet/firsat taramasi
  rakipbul   -> DISPATCH_ARGUMENT'taki fikir icin rakip analizi
  maliyet    -> DISPATCH_ARGUMENT'taki fikir icin altyapi maliyet analizi
"""

import os
import sys

from scanner import (
    SUBREDDITS,
    analyze_cost,
    analyze_pain_points,
    chunk_text,
    fetch_reddit_pain_points,
    logger,
    research_competitors,
    run_scan_and_notify,
    send_telegram_message,
    validate_config,
)


def run_tara():
    run_scan_and_notify(trigger_source="manual")


def run_trendler():
    pain_data = fetch_reddit_pain_points(SUBREDDITS)
    if not pain_data:
        send_telegram_message(
            ["🚨 *Haftanın Acı Noktaları ve Fırsatlar*\n\nBu hafta kriterlere uyan şikayet gönderisi bulunamadı."]
        )
        logger.info("Sikayet kriterine uyan gonderi bulunamadi.")
        return

    result_text = analyze_pain_points(pain_data)
    message = f"🚨 *Haftanın Acı Noktaları ve Fırsatlar*\n\n{result_text}"
    send_telegram_message(chunk_text(message))
    logger.info("Trend/sikayet taramasi tamamlandi.")


def run_rakipbul(argument):
    if not argument:
        send_telegram_message(
            ["⚠️ Kullanım: /rakipbul <fikir veya proje adı>\nÖrnek: /rakipbul Notion benzeri sade not alma uygulaması"]
        )
        return

    result_text = research_competitors(argument)
    message = f"🥊 *Rakip Analizi: {argument}*\n\n{result_text}"
    send_telegram_message(chunk_text(message))
    logger.info("Rakip analizi tamamlandi.")


def run_maliyet(argument):
    if not argument:
        send_telegram_message(
            ["⚠️ Kullanım: /maliyet <fikir veya proje adı>\nÖrnek: /maliyet Notion benzeri sade not alma uygulaması"]
        )
        return

    result_text = analyze_cost(argument)
    message = f"💸 *Maliyet Analizi: {argument}*\n\n{result_text}"
    send_telegram_message(chunk_text(message))
    logger.info("Maliyet analizi tamamlandi.")


COMMAND_HANDLERS = {
    "tara": run_tara,
    "trendler": run_trendler,
}

ARG_COMMAND_HANDLERS = {
    "rakipbul": run_rakipbul,
    "maliyet": run_maliyet,
}


def main():
    try:
        validate_config()
    except EnvironmentError as exc:
        logger.critical(exc)
        sys.exit(1)

    command = os.getenv("DISPATCH_COMMAND", "").strip().lower()
    argument = os.getenv("DISPATCH_ARGUMENT", "").strip()

    if not command:
        logger.critical("DISPATCH_COMMAND ortam degiskeni bos, calistirilacak komut belli degil.")
        sys.exit(1)

    logger.info("Komut alindi: %s", command)

    try:
        if command in ARG_COMMAND_HANDLERS:
            ARG_COMMAND_HANDLERS[command](argument)
        elif command in COMMAND_HANDLERS:
            COMMAND_HANDLERS[command]()
        else:
            logger.warning("Bilinmeyen komut: %s", command)
            sys.exit(1)
    except Exception as exc:
        logger.error("Komut calistirilirken hata olustu (%s): %s", command, exc)
        send_telegram_message([f"❌ '{command}' komutu sırasında hata oluştu: {exc}"])
        sys.exit(1)


if __name__ == "__main__":
    main()

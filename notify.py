"""
Firsat Avcisi - zamanlanmis bildirim girisi.

Cron ile gunde iki kez (09:00 ve 21:00) tetiklenir, bir tarama yapip
Telegram'a bulten gonderir, isi bitince surec kapanir. Sonsuz donguye
GIRMEZ; zamanlama tamamen cron tarafindan yapilir.
"""

import sys

from scanner import logger, run_scan_and_notify


def main():
    try:
        run_scan_and_notify(trigger_source="scheduled")
    except Exception as exc:
        logger.critical("Zamanlanmis tarama basarisiz: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

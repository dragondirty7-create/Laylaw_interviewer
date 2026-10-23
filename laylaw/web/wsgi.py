"""Production entry point: ``waitress-serve --listen=127.0.0.1:8080 laylaw.web.wsgi:app``.

Run behind an HTTPS reverse proxy (set LAYLAW_TRUST_PROXY=1). Configuration comes
only from the environment: LAYLAW_DATA_DIR, LAYLAW_MASTER_KEY.
"""
import logging

from .app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = create_app()

"""Gunicorn entry point."""

from . import create_app
from .services.hardening import install_runtime_hardening

app = create_app()
install_runtime_hardening(app)


if __name__ == "__main__":
    settings = app.config["APP_SETTINGS"]
    app.run(host="0.0.0.0", port=8099, debug=settings.debug)

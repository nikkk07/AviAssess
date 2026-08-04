"""
Keep-alive module to prevent Render free-tier spin-down.

WHY this exists:
    Render's free tier spins down after 15 minutes of inactivity. A cold start
    costs 30-60 seconds (model loading). This module self-pings the /api/health
    endpoint every 10 minutes to keep the instance warm.

HOW it works:
    A background thread runs in a loop, sleeping 10 minutes between pings.
    The ping only happens when RENDER_EXTERNAL_URL is set (production), so local
    dev is unaffected.

USAGE:
    Import and call start_keepalive() once during app startup (main.py lifespan).
"""

import os
import logging
import threading
import time

import requests


logger = logging.getLogger(__name__)

# How often to ping (in seconds). 10 minutes = 600 seconds.
# Render spins down after 15 minutes idle, so 10 min keeps us safely warm.
PING_INTERVAL_SECONDS = 600

_keepalive_thread = None
_should_stop = threading.Event()


def self_ping() -> None:
    """
    Ping this service's own /api/health endpoint to keep it alive.

    Only runs when RENDER_EXTERNAL_URL is set (production). Local dev is skipped.
    """
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        # Not on Render — local dev or missing env var. Skip silently.
        return

    health_url = f"{url}/api/health"

    try:
        r = requests.get(health_url, timeout=10)
        logger.info("Keep-alive ping OK → %s (status %d)", health_url, r.status_code)
    except Exception as exc:  # noqa: BLE001 — best-effort, never fatal
        logger.warning("Keep-alive ping failed (will retry): %s", exc)


def _keepalive_loop() -> None:
    """
    Background loop: sleep, ping, repeat.

    Runs until _should_stop is set (app shutdown).
    """
    logger.info("Keep-alive thread started (ping interval: %d seconds)", PING_INTERVAL_SECONDS)

    while not _should_stop.is_set():
        # Wait for the interval OR until stop is signaled
        if _should_stop.wait(timeout=PING_INTERVAL_SECONDS):
            # Stop was signaled — exit loop
            break

        self_ping()

    logger.info("Keep-alive thread stopped")


def start_keepalive() -> None:
    """
    Start the keep-alive background thread.

    Call this ONCE during app startup (e.g., in the FastAPI lifespan).
    Safe to call multiple times — only one thread will run.
    """
    global _keepalive_thread

    if _keepalive_thread is not None and _keepalive_thread.is_alive():
        logger.warning("Keep-alive thread already running — skipping start")
        return

    _should_stop.clear()
    _keepalive_thread = threading.Thread(target=_keepalive_loop, daemon=True, name="keepalive")
    _keepalive_thread.start()


def stop_keepalive() -> None:
    """
    Signal the keep-alive thread to stop and wait for it to exit.

    Call this during app shutdown (e.g., in the FastAPI lifespan).
    """
    global _keepalive_thread

    if _keepalive_thread is None or not _keepalive_thread.is_alive():
        return

    logger.info("Stopping keep-alive thread...")
    _should_stop.set()
    _keepalive_thread.join(timeout=5)  # Wait up to 5 seconds for clean exit

    if _keepalive_thread.is_alive():
        logger.warning("Keep-alive thread did not stop cleanly")
    else:
        logger.info("Keep-alive thread stopped")

    _keepalive_thread = None

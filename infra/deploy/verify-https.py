"""Require TLS verification and real public API JSON, never a SPA fallback."""

import json
import os
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def verify(origin, attempts=12, delay=5):
    if not origin.startswith("https://"):
        raise ValueError("Public probe requires HTTPS")
    for attempt in range(attempts):
        try:
            for path, expected_status, expected in [
                ("/api/ready", 200, {"status": "ready"}),
                ("/api/v1/auth/me", 401, None),
            ]:
                try:
                    response = urlopen(
                        origin + path, timeout=10, context=ssl.create_default_context()
                    )
                except HTTPError as error:
                    response = error
                with response:
                    if (
                        response.getcode() != expected_status
                        or response.headers.get_content_type() != "application/json"
                    ):
                        raise ValueError("Unexpected public API status/content type")
                    data = json.loads(response.read(65536))
                    if expected is not None and data != expected:
                        raise ValueError(
                            "Public readiness did not return expected JSON"
                        )
                    if (
                        expected is None
                        and data.get("error", {}).get("code") != "unauthenticated"
                    ):
                        raise ValueError(
                            "Public auth response did not come from expected API"
                        )
            return
        except (URLError, OSError, ValueError):
            if attempt + 1 == attempts:
                raise
            time.sleep(delay)


if __name__ == "__main__":
    try:
        verify(
            sys.argv[1],
            attempts=int(os.environ.get("STAYHUB_PROBE_ATTEMPTS", "12")),
            delay=float(os.environ.get("STAYHUB_PROBE_DELAY", "5")),
        )
        print("Public HTTPS readiness and unauthenticated API checks passed")
    except (URLError, OSError, ValueError):
        raise SystemExit("Public HTTPS API verification failed") from None

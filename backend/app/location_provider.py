"""Small fixed Geoapify boundary. Never log URLs, queries or exception bodies."""

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.errors import ApiError

ENDPOINT = "https://api.geoapify.com/v1/geocode/autocomplete"
MAX_BYTES = 131072


class Suggestion(BaseModel):
    display_address: str = Field(min_length=1, max_length=300)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def unavailable() -> ApiError:
    return ApiError(
        503,
        "location_unavailable",
        "Address suggestions are unavailable. Enter your address and pin manually.",
        {"Retry-After": "60"},
    )


def fetch_suggestions(query: str, key: str) -> list[Suggestion]:
    params = urllib.parse.urlencode(
        {"text": query, "limit": 5, "format": "json", "apiKey": key}
    )
    request = urllib.request.Request(
        ENDPOINT + "?" + params, headers={"Accept": "application/json"}
    )
    try:
        # Redirects cannot move this credential-bearing request to another origin.
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=4
        ) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise unavailable()
        document = json.loads(raw)
        results = document.get("results") if isinstance(document, dict) else None
        if not isinstance(results, list) or len(results) > 5:
            raise unavailable()
        suggestions = []
        for result in results:
            if not isinstance(result, dict):
                raise unavailable()
            address, lat, lon = (
                result.get("formatted"),
                result.get("lat"),
                result.get("lon"),
            )
            if (
                not isinstance(address, str)
                or not isinstance(lat, (int, float))
                or isinstance(lat, bool)
                or not isinstance(lon, (int, float))
                or isinstance(lon, bool)
                or not math.isfinite(lat)
                or not math.isfinite(lon)
            ):
                raise unavailable()
            suggestions.append(
                Suggestion(display_address=address.strip(), latitude=lat, longitude=lon)
            )
        return suggestions
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise ApiError(
                429,
                "location_rate_limited",
                "Address suggestions are busy. Wait before searching again, or enter a pin manually.",
                {"Retry-After": "60"},
            ) from None
        raise unavailable() from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, ValidationError):
        raise unavailable() from None

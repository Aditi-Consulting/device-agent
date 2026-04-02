"""Thin HTTP client that wraps the Device API endpoints."""

from __future__ import annotations

import logging

import requests
from requests import Response

from src.device_agent.config import settings

logger = logging.getLogger(__name__)


class DeviceAPIError(Exception):
    """Raised when the Device API returns an unexpected response."""


def _post(url: str, payload: dict) -> dict:
    """Execute a POST request and return the parsed JSON body.

    Args:
        url:     Fully-qualified endpoint URL.
        payload: JSON-serialisable request body.

    Returns:
        Parsed JSON response as a dictionary.

    Raises:
        DeviceAPIError: On network errors or non-2xx HTTP responses.
    """
    try:
        logger.debug("POST %s  payload=%s", url, payload)
        response: Response = requests.post(
            url,
            json=payload,
            timeout=settings.api_timeout,
        )
        response.raise_for_status()
        data: dict = response.json()
        logger.debug("Response %s  body=%s", response.status_code, data)
        return data
    except requests.exceptions.HTTPError as exc:
        raise DeviceAPIError(
            f"HTTP {exc.response.status_code} from {url}: {exc.response.text}"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise DeviceAPIError(f"Network error calling {url}: {exc}") from exc


def check_eligibility(imei: str) -> bool:
    """Return *True* if the device is eligible for unlocking.

    Args:
        imei: Device IMEI string.

    Returns:
        Boolean eligibility flag.

    Raises:
        DeviceAPIError: When the API call fails.
    """
    data = _post(settings.eligibility_url, {"imei": imei})
    return bool(data.get("eligible", False))


def unlock_device(imei: str) -> str:
    """Request a device unlock and return the status message.

    Args:
        imei: Device IMEI string.

    Returns:
        Status message from the API (e.g. ``"success"``).

    Raises:
        DeviceAPIError: When the API call fails.
    """
    data = _post(settings.unlock_url, {"imei": imei})
    return str(data.get("status", "unknown"))


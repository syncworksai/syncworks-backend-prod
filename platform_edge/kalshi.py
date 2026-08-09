import base64
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


BASE_URLS = {
    "LIVE": "https://external-api.kalshi.com/trade-api/v2",
    "DEMO": "https://external-api.demo.kalshi.co/trade-api/v2",
}


def _signature(private_key_pem: str, timestamp: str, method: str, path: str) -> str:
    private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    message = f"{timestamp}{method.upper()}/trade-api/v2{path}".encode("utf-8")
    signed = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signed).decode("utf-8")


def get_balance(api_key_id: str, private_key_pem: str, environment: str) -> dict:
    base_url = BASE_URLS[environment]
    path = "/portfolio/balance"
    timestamp = str(int(time.time() * 1000))
    headers = {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": _signature(private_key_pem, timestamp, "GET", path),
    }
    response = requests.get(f"{base_url}{path}", headers=headers, timeout=10)
    if response.status_code != 200:
        detail = "Kalshi rejected the API credentials."
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message") or payload.get("message") or detail
        except ValueError:
            pass
        raise ValueError(detail)
    return response.json()

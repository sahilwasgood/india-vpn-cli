import hashlib
import hmac
import json
import time
import uuid
import requests

BASE = "https://api.nexthour.app"
API_KEY = "M7xE_IGzlrwjYm42"
HMAC_KEY = b"rfh9BliTmLyNZy3SXWGGtT6uQQJiU5yP1RtON-XuALYSedYx"
APP_PKG = "com.ispvpn.securevpn"
APP_SIG = "985667ce4fb4e93e690a25e12a5a8660ceffebf9cd127c40302d64ba5a6c8e00"
DEVICE_ID = "lookup-cli-" + uuid.uuid4().hex[:12]


def sign(method, body: bytes, ts: str) -> str:
    canon = "\n".join([method.upper(), str(len(body)), ts, hashlib.sha256(body).hexdigest()])
    return hmac.new(HMAC_KEY, canon.encode(), hashlib.sha256).hexdigest()


def headers(method, body: bytes, extra_ctx=False):
    ts = str(int(time.time()))
    h = {
        "X-Api-Key": API_KEY,
        "X-Timestamp": ts,
        "X-Signature": sign(method, body, ts),
    }
    if extra_ctx:
        h.update({
            "X-App-Package": APP_PKG,
            "X-App-Signature": APP_SIG,
            "X-App-Version-Code": "182",
            "X-Device-Id": DEVICE_ID,
            "X-Install-Source": "com.android.vending",
            "User-Agent": "okhttp/4.12.0",
        })
    return h


def try_req(method, path, body_obj=None, extra_ctx=False, tok=None):
    body = json.dumps(body_obj).encode() if body_obj is not None else b""
    h = headers(method, body, extra_ctx)
    if body_obj is not None:
        h["Content-Type"] = "application/json"
    if tok:
        h["X-Session-Token"] = tok
        h["Authorization"] = "Bearer " + tok
    r = requests.request(method, BASE + path, data=body or None, headers=h, timeout=25)
    return r


if __name__ == "__main__":
    print("device:", DEVICE_ID)
    for name, extra in [("minimal", False), ("with-app-headers", True)]:
        for path in ["/api/config", "/api/health"]:
            r = try_req("GET", path, extra_ctx=extra)
            print(f"[{name}] GET {path}: {r.status_code} {r.text[:120]}")
    body = {"device_id": DEVICE_ID, "platform": "android", "device_model": "Pixel 7",
            "manufacturer": "Google", "os_version": "14", "app_name": "India VPN", "app_version": "32.0"}
    r = try_req("POST", "/api/users/register-device", body, extra_ctx=True)
    print("register-device:", r.status_code, r.text[:400])

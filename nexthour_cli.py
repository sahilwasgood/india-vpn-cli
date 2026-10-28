#!/usr/bin/env python3
"""India VPN (com.ispvpn.securevpn v32.0) API client + tunnel manager.

Reconstructed from static RE of base.apk + libappsigner.so and verified live
(the canonical formula was confirmed byte-for-byte against a captured app
request; the CLI mints sessions, fetches server configs and runs them).

Flow
  register  -> POST /api/users/register-device      (anonymous session)
  servers   -> GET  /api/servers                    (32 servers)
  config    -> GET  /api/servers/{id}/config        (VLESS share link)
  peer      -> POST /api/servers/{id}/wireguard/peer (WireGuard peer)
  up/down   -> sing-box (VLESS+REALITY) or wg-quick (WireGuard)

Signing (verified):
  canonical = METHOD \\n PATH \\n TIMESTAMP \\n sha256hex(body)
              [\\n cert_sha256] [\\n tamper_state] [\\n install_source]
  signature = hex(HMAC-SHA256(secret, canonical))       headers X-Api-Key /
  X-Timestamp / X-Signature + X-App-* identity headers.

Free-tier India gateway: id 281 (v2ray/vless, Contabo/AWS 13.140.74.244),
id 282 (wireguard, same host). Premium Mumbai: id 251 / 253.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

import requests

BASE = "https://api.nexthour.app"
API_KEY = "M7xE_IGzlrwjYm42CWvO28cxTztF0oW7"
HMAC_SECRET = b"rfh9BliTmLyNZy3SXWGGtT6uQQJiU5yP1RtON-XuALYSedYx"
APP_PKG = "com.ispvpn.securevpn"
APP_VER_CODE = "182"
# cert sha256 of the official Play build (registered server-side)
APP_SIGNATURE = "985667ce4fb4e93e690a25e12a5a8660ceffebf9cd127c40302d64ba5a6c8e00"
TAMPER_STATE = "usb_debugging"
INSTALL_SOURCE = "com.android.vending"
STATE_DIR = os.path.expanduser("~/.config/nexthour")
STATE = os.path.join(STATE_DIR, "session.json")
SB_DIR = os.path.join(STATE_DIR, "sing-box")


def state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save(**kw):
    os.makedirs(STATE_DIR, exist_ok=True)
    s = state()
    s.update(kw)
    os.umask(0o077)
    json.dump(s, open(STATE, "w"), indent=1)


def sign(method, path, body, ts, cert=APP_SIGNATURE, tamper=TAMPER_STATE, install=INSTALL_SOURCE):
    parts = [method.upper(), path, ts, hashlib.sha256(body).hexdigest()]
    if cert:
        parts.append(cert)
    if tamper:
        parts.append(tamper.lower())
    if install:
        parts.append(install.lower())
    return hmac.new(HMAC_SECRET, "\n".join(parts).encode(), hashlib.sha256).hexdigest()


def api(method, path, body_obj=None, timeout=25):
    st = state()
    dev = st.get("device_id") or uuid.uuid4().hex[:16]
    if not st.get("device_id"):
        save(device_id=dev)
    body = json.dumps(body_obj).encode() if body_obj is not None else b""
    ts = str(int(time.time()))
    headers = {
        "X-Api-Key": API_KEY,
        "X-Timestamp": ts,
        "X-Signature": sign(method, path, body, ts),
        "X-App-Package": APP_PKG,
        "X-App-Version-Code": APP_VER_CODE,
        "X-App-Signature": APP_SIGNATURE,
        "X-Tamper-State": TAMPER_STATE,
        "X-Install-Source": INSTALL_SOURCE,
        "X-Device-Id": dev,
        "User-Agent": "okhttp/4.12.0",
    }
    if st.get("session_token"):
        headers["X-Session-Token"] = st["session_token"]
    if body_obj is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    return requests.request(method, BASE + path, data=body or None, headers=headers, timeout=timeout)


def cmd_register(_a):
    st = state()
    dev = st.get("device_id") or uuid.uuid4().hex[:16]
    body = {"device_id": dev, "android_id": dev, "device_model": "Generic", "manufacturer": "generic",
            "platform": "android", "os_version": "Android 15 (API 35)", "app_name": "India VPN",
            "app_version": "32.0", "is_rooted": False, "root_indicators": []}
    r = api("POST", "/api/users/register-device", body)
    print(r.status_code, r.text[:300])
    if r.ok and r.json().get("session_token"):
        save(device_id=dev, session_token=r.json()["session_token"], user_id=r.json().get("user_id"))
        print("session saved")
    return 0 if r.ok else 2


def ensure_session():
    if not state().get("session_token"):
        print("no session - running register", file=sys.stderr)
        cmd_register(None)


def cmd_servers(a):
    ensure_session()
    r = api("GET", "/api/servers")
    if not r.ok:
        print(r.status_code, r.text[:300])
        return 2
    items = r.json().get("items", [])
    for s in items:
        if a.filter and a.filter.lower() not in json.dumps(s).lower():
            continue
        print(f'{s.get("id"):>4} {s.get("protocol"):<9} {s.get("country"):<14} {s.get("location"):<12} '
              f'{s.get("tier") or "":<8} {s.get("sub_protocol") or "":<5} {s.get("note") or ""}')
    return 0


def get_config(server_id):
    r = api("GET", f"/api/servers/{server_id}/config")
    if not r.ok:
        raise SystemExit(f"{r.status_code} {r.text[:200]}")
    return r.json()


def cmd_config(a):
    c = get_config(a.server_id)
    print(json.dumps(c, indent=1)[:4000])
    return 0


def vless_to_outbound(cfg):
    """Parse a vless:// share link into a sing-box outbound."""
    from urllib.parse import urlparse, parse_qs, unquote
    link = None
    for cand in [cfg.get("config")] + [c.get("config") for c in cfg.get("configs", [])]:
        if cand and cand.startswith("vless://"):
            link = cand
            break
    if not link:
        raise SystemExit("no vless link in config")
    u = urlparse(link)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    out = {
        "type": "vless", "tag": "vpn",
        "server": u.hostname, "server_port": u.port or 443,
        "uuid": unquote(u.username or ""),
    }
    if q.get("flow"):
        out["flow"] = q["flow"]
    if q.get("packetEncoding"):
        out["packet_encoding"] = q["packetEncoding"]
    tls = {"enabled": True, "server_name": q.get("sni") or u.hostname}
    if q.get("fp"):
        tls["utls"] = {"enabled": True, "fingerprint": q["fp"]}
    if q.get("security") == "reality":
        tls["reality"] = {"enabled": True, "public_key": q.get("pbk", ""), "short_id": q.get("sid", "")}
    out["tls"] = tls
    transport = {"type": q.get("type") or "tcp"}
    if q.get("path"):
        transport["path"] = q["path"]
    if q.get("host"):
        transport["host"] = q["host"]
    if transport["type"] != "tcp":
        out["transport"] = transport
    return out


def find_singbox():
    for p in (shutil.which("sing-box"), os.path.join(SB_DIR, "sing-box")):
        if p and os.path.exists(p):
            return p
    os.makedirs(SB_DIR, exist_ok=True)
    ver = "1.11.15"
    url = f"https://github.com/SagerNet/sing-box/releases/download/v{ver}/sing-box-{ver}-linux-amd64.tar.gz"
    print("downloading sing-box...", file=sys.stderr)
    subprocess.run(f"cd {SB_DIR} && curl -sL --max-time 180 -o sb.tgz '{url}' && tar xzf sb.tgz "
                   f"&& cp sing-box-{ver}-linux-amd64/sing-box . && chmod +x sing-box && rm -rf sb.tgz sing-box-{ver}-linux-amd64",
                   shell=True, check=True)
    return os.path.join(SB_DIR, "sing-box")


def cmd_up(a):
    ensure_session()
    cfg = get_config(a.server_id)
    ob = vless_to_outbound(cfg)
    mixed_port = a.port
    conf = {
        "log": {"level": "warn"},
        "inbounds": [{"type": "mixed", "tag": "in", "listen": "127.0.0.1", "listen_port": mixed_port}],
        "outbounds": [ob],
    }
    path = os.path.join(STATE_DIR, f"sb-{a.server_id}.json")
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump(conf, open(path, "w"), indent=1)
    sb = find_singbox()
    logf = os.path.join(STATE_DIR, f"sb-{a.server_id}.log")
    subprocess.run(["pkill", "-f", f"sing-box run -c {path}"], capture_output=True)
    subprocess.Popen([sb, "run", "-c", path], stdout=open(logf, "w"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    time.sleep(2)
    # verify egress
    try:
        r = requests.get(BASE + "/api/site/visitor", proxies={"http": f"socks5h://127.0.0.1:{mixed_port}",
                                                             "https": f"socks5h://127.0.0.1:{mixed_port}"}, timeout=20)
        info = r.json()
        print(f"tunnel up on socks5://127.0.0.1:{mixed_port} -> exit {info.get('ip')} ({info.get('country')})")
        save(vpn_server=a.server_id, vpn_port=mixed_port)
        return 0 if info.get("country_code") == "IN" else 3
    except Exception as e:
        print("tunnel check failed:", e, file=sys.stderr)
        return 2


def cmd_down(_a):
    subprocess.run(["pkill", "-f", "sing-box run -c"], capture_output=True)
    print("tunnel stopped")
    return 0


def cmd_wireguard(a):
    ensure_session()
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    k = X25519PrivateKey.generate()
    priv = base64.b64encode(k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                            serialization.NoEncryption())).decode()
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw,
                                                       serialization.PublicFormat.Raw)).decode()
    r = api("POST", f"/api/servers/{a.server_id}/wireguard/peer",
            {"public_key": pub, "device_id": state()["device_id"]})
    if not r.ok:
        print(r.status_code, r.text[:200])
        return 2
    p = r.json()
    conf = (f"[Interface]\nPrivateKey = {priv}\nAddress = {p.get('assigned_ip')}\n"
            f"DNS = {p.get('dns') or '1.1.1.1'}\nMTU = {p.get('mtu', 1280)}\n\n[Peer]\n"
            f"PublicKey = {p.get('server_public_key')}\n"
            + (f"PresharedKey = {p['preshared_key']}\n" if p.get("preshared_key") else "")
            + f"AllowedIPs = {p.get('allowed_ips')}\nEndpoint = {p.get('endpoint')}\n"
            f"PersistentKeepalive = {p.get('persistent_keepalive', 25)}\n")
    out = a.out or os.path.join(STATE_DIR, f"wg-{a.server_id}.conf")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    os.umask(0o077)
    open(out, "w").write(conf)
    print("wrote", out, "| endpoint", p.get("endpoint"), "| ip", p.get("assigned_ip"))
    return 0


def cmd_status(_a):
    s = state()
    try:
        r = requests.get(BASE + "/api/site/visitor", timeout=10)
        ip = r.json()
    except Exception:
        ip = {}
    print(json.dumps({"device_id": s.get("device_id"), "session": bool(s.get("session_token")),
                      "vpn_server": s.get("vpn_server"), "vpn_port": s.get("vpn_port"),
                      "direct_egress": ip}, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser(description="India VPN API client (verified RE)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("register").set_defaults(fn=cmd_register)
    p = sub.add_parser("servers"); p.add_argument("--filter"); p.set_defaults(fn=cmd_servers)
    p = sub.add_parser("config"); p.add_argument("server_id", type=int); p.set_defaults(fn=cmd_config)
    p = sub.add_parser("up"); p.add_argument("server_id", type=int, nargs="?", default=281); p.add_argument("--port", type=int, default=2080); p.set_defaults(fn=cmd_up)
    sub.add_parser("down").set_defaults(fn=cmd_down)
    p = sub.add_parser("wireguard"); p.add_argument("server_id", type=int); p.add_argument("--out"); p.set_defaults(fn=cmd_wireguard)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

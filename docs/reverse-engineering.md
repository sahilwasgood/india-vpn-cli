# India VPN (com.ispvpn.securevpn) — reverse-engineering report

Target: `base.apk` v32.0 (versionCode 182) pulled from the phone via adb, sha256
`c5abf45c78301df0c88adecfa82da227ebf7841a4bae5620204934446ebc9d0f`, plus
`split_config.arm64_v8a.apk` (native libs).

## What the app is

- Kotlin/Compose client for **Next Hour VPN** (`nexthour.app`), backend
  `vpn-admin-api` (FastAPI) at **https://api.nexthour.app** (host assembled in
  `libappsigner.so` from `"https://"` + `"api.next"` + `"hour.app"` + `"/"`; the
  stray `"api.nextfatal"` string is a decoy tail).
- Two tunnel technologies:
  - **Xray-core** (`libgojni.so` 33 MB, assets `geoip.dat` / `geosite.dat`) —
    VLESS + REALITY gateways, installed server-side by the open
    `GET https://api.nexthour.app/install.sh` script (VLESS+REALITY, chrome
    uTLS, XTLS Vision, tuned for gaming; prints a share link for the admin
    panel).
  - **WireGuard** (`libwg-go.so`, `libwg-quick.so`) — API-minted peers.
- API surface (public OpenAPI spec at `/openapi.json`, 245 paths): OTP/email
  auth, anonymous device registration, server list, per-server configs,
  WireGuard peer minting, subscriptions (Google Play / Stripe / NOWPayments),
  admin panel endpoints.

## Client handshake (from dex `Lsa;` + native `libappsigner.so`)

Every `/api/*` request carries:

| header | value |
|---|---|
| X-Api-Key | `M7xE_IGzlrwjYm42CWvO28cxTztF0oW7` (32 chars, extracted 0x14df0+0x14e10) |
| X-Timestamp | unix seconds |
| X-Signature | `hex(HMAC-SHA256(secret, canonical))` |
| X-App-Package | `com.ispvpn.securevpn` |
| X-App-Version-Code | `182` |
| X-App-Signature | cert sha256: `985667ce…8e00` (apksigner) |
| X-Device-Id | install UUID |
| X-Install-Source | `com.android.vending` (X-Tamper-State optional) |

HMAC secret (48 chars, XOR-obfuscated in `.so` at 0x16860 ^ 0x168b0):
`rfh9BliTmLyNZy3SXWGGtT6uQQJiU5yP1RtON-XuALYSedYx`

Canonical string (`Lsa;->c`, SHA-256 hex of body from `Lsa;->H`):
```
METHOD\n<contentLength>\n<timestamp>\n<sha256hex(body)>[\n<cert_sha256>[\n<tamper_state>[\n<install_source>]]]
```

The admin panel (JS bundle of nexthour.app) confirms the scheme: "Every public
endpoint requires X-Api-Key + X-Timestamp + X-Signature headers and rejects
anything else with 401" — keys are managed under Settings → Security ("API key"
= `secrets.token_urlsafe(24)`, "API secret (HMAC key)" =
`secrets.token_urlsafe(36)`), embedded into the app via
`tools/obfuscate_signer_keys.py` → `native_signer.cpp`.

## Endpoints needed for a CLI tunnel

```
POST /api/users/register-device   {device_id, platform, ...} -> {session_token}
GET  /api/servers                 -> {items:[{id, protocol, country, ...}]}
GET  /api/servers/{id}/config     -> {config: "<vless://...>", dns, ...}
POST /api/servers/{id}/wireguard/peer
     {public_key, device_id}
     -> {server_public_key, endpoint, assigned_ip, allowed_ips, dns, mtu,
         persistent_keepalive, preshared_key}
POST /api/servers/{id}/wireguard/peer/disconnect
```

## Status

- APK pulled, unpacked, decompiled; full API map + signing scheme + both
  secrets + cert fingerprint extracted (`observed`).
- `nexthour_cli.py selftest` replays the handshake with the extracted values:
  the live API still answers **401 {"detail":"Authentication required."}**
  across 60+ canonical/header permutations (`observed`).
- Interpretation (`inferred`): either the server's stored key/secret pair was
  rotated after v32.0 shipped (the panel explicitly warns that stale APKs 401
  until rebuilt), or the canonical includes one more field not visible in the
  decompiled interceptor. A single capture of one real app request settles it
  in seconds - `adb shell settings put global http_proxy <pc>:8080` +
  mitmproxy with the mitm CA, launch the app, read the `/api/config` request.

## Files

- `base.apk`, `split_config.*.apk` - pulled artifacts (`watch/apks/india-vpn/`)
- `unpack/` - manifest, dex, native libs, assets
- `nexthour_openapi.json` - the complete public API spec (558 KB)
- `nexthour_cli.py` - CLI implementation of the flow (register / login /
  servers / config / wireguard / status; `selftest` probes the handshake)

## UPDATE — handshake SOLVED (live verified)

Capture method: apk-mitm route failed on API-37 resources; used apktool 2.11.1
with a patched `network_security_config` (system+user+@raw/nxca mitm CA bundled)
and a 3-line smali patch in `sa.smali` that logs the canonical
(`Log.d("CANON", v14)`) before signing. One launch later the canonical was:

    METHOD \n PATH \n TIMESTAMP \n sha256hex(body) [\n cert_sha256 [\n tamper [\n install_source]]]

NOTE: line 2 is the request PATH, not the body length (decompiler mislead), and
line 3 the unix seconds from X-Timestamp. Verified offline: HMAC(secret, canon)
equals the captured X-Signature byte-for-byte. Verified live: register-device
200, /api/config 200, /api/servers 200 (32 servers).

Free-tier India gateways: id 281 (v2ray/vless, 13.140.74.244, Contabo note),
id 282 (wireguard, same host). Premium: 251/253 Mumbai (Akamai). The vless
share link is VLESS+REALITY (sni www.icloud.com, xtls-rprx-vision, xudp).

Working CLI: `watch/nexthour/nexthour_cli.py`
  register → servers --filter india → up 281 (downloads sing-box, runs
  socks5 127.0.0.1:2080) → exit IP 13.140.74.244 (India), national portals
  (impds.nic.in, nfsa.gov.in) reachable through the tunnel; `wireguard <id>`
  writes a wg-quick conf from a freshly minted peer (282); `down` stops.

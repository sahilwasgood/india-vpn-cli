# india-vpn-cli

Unofficial CLI for the **India VPN** Android app (`com.ispvpn.securevpn`, Next Hour)
— a reverse-engineered client for its public API that brings up the app's own
VPN gateways from a terminal, so Indian-IP-gated services (government portals
included) can be reached from any machine.

Not affiliated with Next Hour / India VPN. Use your own judgement about the
acceptable use of a third-party service.

## What it does

The Android app talks to `https://api.nexthour.app` (FastAPI) with signed
requests and runs Xray-core (VLESS + REALITY) and WireGuard tunnels. This CLI
reproduces the client side:

```
register  -> POST /api/users/register-device        (anonymous session)
servers   -> GET  /api/servers                      (32 gateways, 4 India)
up        -> GET  /api/servers/{id}/config          (VLESS share link)
             -> sing-box (VLESS+REALITY) on socks5://127.0.0.1:2080
wireguard -> POST /api/servers/{id}/wireguard/peer  (WireGuard peer, wg-quick conf)
down      -> stop the tunnel
```

## Request signing (the interesting part)

Every `/api` call carries `X-Api-Key` + `X-Timestamp` + `X-Signature` and is
rejected with 401 otherwise. The signature is

```
canonical = METHOD \n PATH \n TIMESTAMP \n sha256hex(body) \
            [ \n app_cert_sha256 [ \n tamper_state [ \n install_source ] ] ]
signature = hex(HMAC-SHA256(secret, canonical))
```

Recovered by static analysis of `base.apk` + `libappsigner.so` and verified
byte-for-byte against live app traffic captured through a repacked build.
See `docs/reverse-engineering.md` for the full trail.

## Install

```
pip install requests cryptography   # cryptography only needed for the wireguard command
curl -sL https://github.com/SagerNet/sing-box/releases/latest ...   # auto-downloaded on first `up`
```

Requires Python 3.10+, `curl` (sing-box download), `bash`.

## Usage

```
python3 nexthour_cli.py register                     # anonymous device session
python3 nexthour_cli.py servers --filter india       # gateways
python3 nexthour_cli.py up 281                       # free India VLESS gateway
curl --socks5-hostname 127.0.0.1:2080 https://impds.nic.in/
python3 nexthour_cli.py wireguard 282 --out wg0.conf # or a WireGuard peer instead
python3 nexthour_cli.py down
```

The session and sing-box live under `~/.config/nexthour/`.

## Free gateways (snapshot 2026-10, all configs verified 200)

`servers.json` carries the full free-tier snapshot (20 gateways, 10 countries).
Every entry below is a free-tier config; `up <id>` works for any of them.

| id | protocol | country | location | host | config |
|----|----------|---------|----------|------|--------|
| 277 | v2ray/vless | BGMI | Server 2 | 148.113.6.149 | ok |
| 275 | wireguard/wg | BGMI | Server 1 | — | ok |
| 263 | v2ray/vless | Canada | Toronto | 216.152.147.231 | ok |
| 266 | wireguard/wg | Canada | Toronto | — | ok |
| 255 | v2ray/vless | France | Paris | 167.17.64.29 | ok |
| 258 | wireguard/wg | France | Paris | — | ok |
| 261 | v2ray/vless | Germany | Frankfurt am Main | 170.101.111.202 | ok |
| 262 | wireguard/wg | Germany | Frankfurt am Main | — | ok |
| 281 | v2ray/vless | India | Marseille | 13.140.74.244 | ok |
| 282 | wireguard/wg | India | Marseille | — | ok |
| 256 | v2ray/vless | Netherlands | Amsterdam | 167.17.70.39 | ok |
| 259 | wireguard/wg | Netherlands | Amsterdam | — | ok |
| 252 | v2ray/vless | Singapore | Singapore | 172.104.33.120 | ok |
| 254 | wireguard/wg | Singapore | Singapore | — | ok |
| 279 | v2ray/vless | Spain | Madrid | 167.17.71.193 | ok |
| 280 | wireguard/wg | Spain | Barcelona | — | ok |
| 257 | v2ray/vless | United Kingdom | London | 136.176.68.58 | ok |
| 260 | wireguard/wg | United Kingdom | London | — | ok |
| 264 | v2ray/vless | United States | Los Angeles | 216.152.152.125 | ok |
| 278 | wireguard/wg | United States | Los Angeles | — | ok |

India specifics (measured):

| id | protocol | host | RTT | tunnel exit | notes |
|----|----------|------|-----|-------------|-------|
| 281 | vless + reality | 13.140.74.244 | ~74 ms | India | works; ~0.3 MB/s free tier |
| 282 | wireguard | 13.140.74.243 | ~126 ms | — | peer mint works; handshake flaky from this host |
| 251 | vless (premium) | Mumbai (Akamai) | — | — | `premium_required` |
| 253 | wireguard (premium) | Mumbai (Akamai) | — | — | `premium_required` |

Government endpoints through the free India tunnel: `impds.nic.in` 200
(~4.5 s), `nfsa.gov.in` 200 (~8 s), ONORC (UMANG) gateway reachable.

## Layout

- `nexthour_cli.py` — the client (session, signing, server list, config, tunnels)
- `docs/reverse-engineering.md` — how the protocol was recovered and verified

## License

MIT — see `LICENSE`.

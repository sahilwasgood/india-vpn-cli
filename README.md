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

## Free India gateways (measured 2026-10)

| id | protocol | host | RTT | tunnel exit | notes |
|----|----------|------|-----|-------------|-------|
| 281 | vless + reality | 13.140.74.244:443 | ~74 ms | India | works; ~0.3 MB/s free tier |
| 282 | wireguard | 13.140.74.243:51820 | ~126 ms | — | peer mint works; handshake flaky from this host |
| 251 | vless (premium) | Mumbai (Akamai) | — | — | `premium_required` |
| 253 | wireguard (premium) | Mumbai (Akamai) | — | — | `premium_required` |

Government endpoints through the free tunnel: `impds.nic.in` 200 (~4.5 s),
`nfsa.gov.in` 200 (~8 s), ONORC (UMANG) gateway reachable.

## Layout

- `nexthour_cli.py` — the client (session, signing, server list, config, tunnels)
- `docs/reverse-engineering.md` — how the protocol was recovered and verified

## License

MIT — see `LICENSE`.

#!/usr/bin/env python3
"""Work out *why* Atlas is unreachable, without leaking the connection string.

ServerSelectionTimeoutError is the same symptom for several very different
causes. This separates them:

  DNS SRV fails            -> DNS egress blocked, or wrong cluster hostname
  SRV ok, TCP 27017 fails  -> egress firewall blocks the Mongo port
  TCP ok, handshake fails  -> credentials / TLS / IP access list
  control 443 fails too    -> no outbound network at all

Prints hostnames partially masked and never prints the URI, user or password.
"""
import os, socket, sys
from urllib.parse import urlsplit, unquote


def mask(h):
    if not h:
        return "?"
    parts = h.split(".")
    return parts[0][:4] + "***." + ".".join(parts[1:]) if len(parts) > 1 else "***"


def tcp(host, port, timeout=8):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except Exception as e:
        return False, type(e).__name__


def main():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        print("FAIL: MONGODB_URI not set"); sys.exit(1)

    sp = urlsplit(uri)
    srv = sp.scheme == "mongodb+srv"
    host = unquote(sp.hostname or "")
    print(f"scheme         : {sp.scheme}")
    print(f"host           : {mask(host)}")

    ok, err = tcp("api.github.com", 443)
    print(f"control 443    : {'ok' if ok else 'FAIL ' + err}")
    if not ok:
        print("=> no outbound network at all from this sandbox"); return

    nodes = []
    if srv:
        try:
            import dns.resolver
        except ImportError:
            print("dnspython missing (pymongo[srv] not installed)"); sys.exit(2)
        try:
            ans = dns.resolver.resolve(f"_mongodb._tcp.{host}", "SRV")
            nodes = [(str(r.target).rstrip("."), r.port) for r in ans]
            print(f"SRV lookup     : ok, {len(nodes)} node(s)")
        except Exception as e:
            print(f"SRV lookup     : FAIL {type(e).__name__}")
            print("=> DNS egress blocked or wrong cluster hostname"); return
    else:
        nodes = [(host, sp.port or 27017)]

    reached = 0
    for h, port in nodes:
        ok, err = tcp(h, port)
        print(f"tcp {mask(h)}:{port} : {'ok' if ok else 'FAIL ' + err}")
        reached += ok

    if not reached:
        print("=> port 27017 is blocked outbound, or every node is down/paused")
        print("   (a paused M0/free cluster looks exactly like this)")
        return

    print("=> TCP reachable; remaining failure is auth, TLS, or the IP access list")


if __name__ == "__main__":
    main()

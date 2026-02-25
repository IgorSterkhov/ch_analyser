#!/usr/bin/env python3
"""Debug script: tries all ClickHouse connection combinations and reports results."""

import argparse
import os
import sys


def try_native(host, port, user, password, secure, ca_cert):
    """Try connecting via clickhouse-driver (native TCP protocol)."""
    from clickhouse_driver import Client as NativeClient

    kwargs = dict(host=host, port=port, user=user, password=password,
                  connect_timeout=5, send_receive_timeout=5)
    if secure:
        kwargs["secure"] = True
        if ca_cert:
            kwargs["ca_certs"] = ca_cert
    client = NativeClient(**kwargs)
    result = client.execute("SELECT 1")
    client.disconnect()
    return result


def try_http(host, port, user, password, secure, ca_cert):
    """Try connecting via clickhouse-connect (HTTP protocol)."""
    import clickhouse_connect

    kwargs = dict(host=host, port=port, username=user, password=password,
                  connect_timeout=5, send_receive_timeout=5)
    if secure:
        kwargs["secure"] = True
        if ca_cert:
            kwargs["verify"] = True
            kwargs["ca_cert"] = ca_cert
        else:
            kwargs["verify"] = False
    client = clickhouse_connect.get_client(**kwargs)
    result = client.query("SELECT 1")
    client.close()
    return result.result_rows


def main():
    parser = argparse.ArgumentParser(description="ClickHouse connection debugger")
    parser.add_argument("--host", required=True, help="ClickHouse server host")
    parser.add_argument("--user", default="default", help="Username (default: default)")
    parser.add_argument("--password", default="", help="Password")
    parser.add_argument("--ca-cert", default="", help="Path to CA certificate (.crt/.pem)")
    args = parser.parse_args()

    ca_cert = args.ca_cert
    if ca_cert and not os.path.isfile(ca_cert):
        print(f"WARNING: CA cert file '{ca_cert}' not found, skipping cert-based tests\n")
        ca_cert = ""

    password_display = "***" if args.password else "(empty)"
    print(f"Host: {args.host}")
    print(f"User: {args.user}")
    print(f"Password: {password_display}")
    print(f"CA cert: {ca_cert or '(none)'}")
    print("=" * 70)

    # Define all combinations to test
    combos = [
        # (label, protocol, port, secure, use_cert)
        ("native  :9000  plain",      "native", 9000, False, False),
        ("native  :9440  SSL",        "native", 9440, True,  False),
        ("native  :9440  SSL+cert",   "native", 9440, True,  True),
        ("http    :8123  plain",      "http",   8123, False, False),
        ("http    :8443  SSL",        "http",   8443, True,  False),
        ("http    :8443  SSL+cert",   "http",   8443, True,  True),
    ]

    results = []
    for label, protocol, port, secure, use_cert in combos:
        cert = ca_cert if use_cert else ""
        if use_cert and not ca_cert:
            results.append((label, "SKIP", "no CA cert provided"))
            continue

        try:
            if protocol == "native":
                try_native(args.host, port, args.user, args.password, secure, cert)
            else:
                try_http(args.host, port, args.user, args.password, secure, cert)
            results.append((label, "OK", ""))
        except Exception as e:
            err = str(e).replace("\n", " ")[:120]
            results.append((label, "FAIL", err))

    # Print results
    print()
    for label, status, detail in results:
        if status == "OK":
            mark = "\033[32mOK\033[0m"
        elif status == "SKIP":
            mark = "\033[33mSKIP\033[0m"
        else:
            mark = "\033[31mFAIL\033[0m"
        line = f"  {label:30s}  [{mark}]"
        if detail:
            line += f"  {detail}"
        print(line)

    # Summary
    ok_list = [r[0].strip() for r in results if r[1] == "OK"]
    print()
    if ok_list:
        print(f"Working connections ({len(ok_list)}):")
        for name in ok_list:
            print(f"  + {name}")
    else:
        print("No working connections found.")


if __name__ == "__main__":
    main()

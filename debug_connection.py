#!/usr/bin/env python3
"""Debug script: tries all ClickHouse connection combinations and reports results."""

import argparse
import os
import re


CONN_PATTERN = re.compile(r"CLICKHOUSE_CONNECTION_(\d+)_(\w+)")
ENV_PATH = ".env"


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
    client.execute("SELECT 1")
    client.disconnect()


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
    client.query("SELECT 1")
    client.close()


def _get_existing_names() -> set[str]:
    """Read existing connection names from .env."""
    names = set()
    if not os.path.isfile(ENV_PATH):
        return names
    with open(ENV_PATH) as f:
        for line in f:
            m = re.match(r"CLICKHOUSE_CONNECTION_\d+_NAME=(.+)", line.strip())
            if m:
                names.add(m.group(1))
    return names


def _next_conn_index() -> int:
    """Find next available connection index in .env."""
    max_idx = 0
    if os.path.isfile(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                m = CONN_PATTERN.match(line.strip().split("=")[0])
                if m:
                    max_idx = max(max_idx, int(m.group(1)))
    return max_idx + 1


def _unique_name(base_name: str, existing: set[str]) -> str:
    """Generate unique connection name, adding suffix if needed."""
    if base_name not in existing:
        return base_name
    for i in range(2, 100):
        candidate = f"{base_name}-{i}"
        if candidate not in existing:
            return candidate
    return base_name


def save_to_env(host, user, password, protocol, port, secure, ca_cert):
    """Append a new connection to .env file."""
    existing_names = _get_existing_names()
    base_name = host.replace(".", "-")
    name = _unique_name(base_name, existing_names)

    if name != base_name:
        print(f"  Connection '{base_name}' already exists, using name '{name}'")

    idx = _next_conn_index()
    prefix = f"CLICKHOUSE_CONNECTION_{idx}_"

    lines = [
        f"{prefix}NAME={name}",
        f"{prefix}HOST={host}",
        f"{prefix}PORT={port}",
        f"{prefix}USER={user}",
        f"{prefix}PASSWORD={password}",
        f"{prefix}PROTOCOL={protocol}",
        f"{prefix}SECURE={str(secure).lower()}",
    ]

    # Ensure CA cert is set globally if needed
    if ca_cert:
        has_ca = False
        if os.path.isfile(ENV_PATH):
            with open(ENV_PATH) as f:
                has_ca = any("CLICKHOUSE_CA_CERT=" in line for line in f)
        if not has_ca:
            lines.insert(0, f"CLICKHOUSE_CA_CERT={ca_cert}")
            print(f"  Added CLICKHOUSE_CA_CERT={ca_cert}")

    with open(ENV_PATH, "a") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  Saved connection '{name}' (index {idx}) to {ENV_PATH}")


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
            results.append((label, "SKIP", "", protocol, port, secure, False))
            continue

        try:
            if protocol == "native":
                try_native(args.host, port, args.user, args.password, secure, cert)
            else:
                try_http(args.host, port, args.user, args.password, secure, cert)
            results.append((label, "OK", "", protocol, port, secure, use_cert))
        except Exception as e:
            err = str(e).replace("\n", " ")[:120]
            results.append((label, "FAIL", err, protocol, port, secure, use_cert))

    # Print results
    print()
    for label, status, detail, *_ in results:
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
    ok_results = [(i, r) for i, r in enumerate(results) if r[1] == "OK"]
    print()
    if not ok_results:
        print("No working connections found.")
        return

    print(f"Working connections ({len(ok_results)}):")
    for num, (_, r) in enumerate(ok_results, 1):
        print(f"  {num}. {r[0].strip()}")

    # Ask user if they want to save
    print()
    choice = input("Save to .env? Enter number (or 'q' to quit): ").strip()
    if choice.lower() in ("q", ""):
        print("Skipped.")
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(ok_results):
            print("Invalid choice.")
            return
    except ValueError:
        print("Invalid input.")
        return

    _, selected = ok_results[idx]
    _, _, _, protocol, port, secure, use_cert = selected
    cert = ca_cert if use_cert else ""
    save_to_env(args.host, args.user, args.password, protocol, port, secure, cert)


if __name__ == "__main__":
    main()

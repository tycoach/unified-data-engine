#!/usr/bin/env python3
"""
Generate a self-signed TLS certificate for local HTTPS development.

Writes to ~/.ude/tls/:
  server.crt  — certificate
  server.key  — private key

Updates ~/.ude/config.yml with:
  use_https: true
  tls_cert: ~/.ude/tls/server.crt
  tls_key:  ~/.ude/tls/server.key

The FastAPI startup command is updated to use:
  uvicorn api.main:app --ssl-keyfile ~/.ude/tls/server.key
                       --ssl-certfile ~/.ude/tls/server.crt

Note: Self-signed certs will show a browser warning — this is expected
for local dev. For production, use Let's Encrypt or a CA-signed cert.
"""

import subprocess
import sys
from pathlib import Path

TLS_DIR  = Path.home() / ".ude" / "tls"
CERT     = TLS_DIR / "server.crt"
KEY      = TLS_DIR / "server.key"


def generate_cert():
    TLS_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating self-signed TLS certificate...")
    result = subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:4096",
        "-keyout", str(KEY),
        "-out",    str(CERT),
        "-days",   "365",
        "-nodes",
        "-subj",   "/C=US/ST=Local/L=Local/O=UDE/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"✗ Failed: {result.stderr}")
        sys.exit(1)

    print(f"✓ Certificate: {CERT}")
    print(f"✓ Private key: {KEY}")


def update_config():
    import yaml
    cfg_file = Path.home() / ".ude" / "config.yml"
    cfg      = {}

    if cfg_file.exists():
        with cfg_file.open() as f:
            cfg = yaml.safe_load(f) or {}

    cfg["use_https"] = True
    cfg["tls_cert"]  = str(CERT)
    cfg["tls_key"]   = str(KEY)
    # Switch port to 8443 for HTTPS
    cfg["port"]      = 8443

    with cfg_file.open("w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    print(f"✓ Config updated: ~/.ude/config.yml")
    print(f"  use_https: true")
    print(f"  port: 8443")


def print_instructions():
    print()
    print("─" * 60)
    print("HTTPS setup complete.")
    print()
    print("Start the API with HTTPS:")
    print(f"  uvicorn api.main:app \\")
    print(f"    --host 0.0.0.0 --port 8443 \\")
    print(f"    --ssl-keyfile {KEY} \\")
    print(f"    --ssl-certfile {CERT}")
    print()
    print("Or run: ude up  (auto-detects TLS config)")
    print()
    print("CLI will automatically use https:// after config update.")
    print()
    print("Note: Your browser will warn about the self-signed cert.")
    print("Add an exception or use: curl -k https://localhost:8443/health")
    print("─" * 60)


if __name__ == "__main__":
    generate_cert()
    update_config()
    print_instructions()
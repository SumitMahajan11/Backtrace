"""Helper script to install and register core Piston packages for all locked v1 languages."""

import os
import sys
import time
import httpx

PACKAGES = [
    ("python", "3.10.0"),
    ("node", "18.15.0"),
    ("typescript", "5.0.3"),
    ("java", "15.0.2"),
    ("rust", "1.68.2"),
    ("go", "1.16.2"),
    ("gcc", "10.2.0"),
    ("bash", "5.2.0"),
]


def install_packages_via_api(piston_url: str = "http://127.0.0.1:2000"):
    """Installs packages via Piston's HTTP API."""
    print(f"[*] Connecting to Piston at {piston_url}...")
    with httpx.Client(timeout=180.0) as client:
        # Wait for Piston API readiness
        for _ in range(15):
            try:
                res = client.get(f"{piston_url}/api/v2/runtimes")
                if res.status_code == 200:
                    break
            except Exception:
                time.sleep(1)
        
        for lang, version in PACKAGES:
            print(f"[*] Installing {lang} {version}...")
            try:
                res = client.post(
                    f"{piston_url}/api/v2/packages",
                    json={"language": lang, "version": version},
                )
                print(f"  Status {res.status_code}: {res.text.strip()}")
            except Exception as e:
                print(f"  Error installing {lang} {version}: {e}")

    # Fetch and verify installed runtimes
    try:
        with httpx.Client(timeout=10.0) as client:
            runtimes = client.get(f"{piston_url}/api/v2/runtimes").json()
            print(f"\n[+] Installation complete. Total runtimes installed: {len(runtimes)}")
            for r in runtimes:
                print(f"  - {r.get('language')} {r.get('version')} (aliases: {r.get('aliases')})")
    except Exception as e:
        print(f"[-] Could not verify runtimes: {e}")


if __name__ == "__main__":
    url = os.getenv("PISTON_URL", "http://127.0.0.1:2000")
    if len(sys.argv) > 1:
        url = sys.argv[1]
    install_packages_via_api(url)

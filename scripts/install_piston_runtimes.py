"""Helper script to install and register core Piston packages."""

import subprocess
import time
import httpx

PACKAGES = [
    ("python", "3.10.0"),
    ("node", "18.15.0"),
    ("bash", "5.2.0"),
]

def install_packages_in_wsl():
    for lang, version in PACKAGES:
        print(f"[*] Installing {lang} {version}...")
        cmd = f"""
        require('nocamel');
        const Package = require('/piston_api/src/package.js');
        (async () => {{
            try {{
                const pkg = await Package.get_package('{lang}', '{version}');
                if (!pkg) {{
                    console.log('Package not found for {lang} {version}');
                    return;
                }}
                if (pkg.installed) {{
                    console.log('{lang} {version} already installed.');
                    return;
                }}
                const res = await pkg.install();
                console.log('Successfully installed {lang} {version}:', res);
            }} catch (e) {{
                console.error('Error installing {lang} {version}:', e.message);
            }}
        }})();
        """
        res = subprocess.run(
            ["wsl", "-d", "Ubuntu", "-u", "root", "--", "docker", "exec", "backtrace_piston", "node", "-e", cmd],
            capture_output=True,
            text=True,
            timeout=120,
        )
        print(f"Stdout: {res.stdout.strip()}")
        if res.stderr:
            print(f"Stderr: {res.stderr.strip()}")

if __name__ == "__main__":
    install_packages_in_wsl()

import httpx
import json

code = """
import ctypes
import os

libc = ctypes.CDLL(None, use_errno=True)

# Syscall numbers on x86_64 Linux:
# 167 = swapon (requires CAP_SYS_ADMIN, which the container HAS)
res_swapon = libc.syscall(167, b"/dev/null", 0)
err_swapon = ctypes.get_errno()

# 246 = kexec_load (requires CAP_SYS_ADMIN, which the container HAS)
res_kexec = libc.syscall(246, 0, 0, 0, 0)
err_kexec = ctypes.get_errno()

# 304 = open_by_handle_at (requires CAP_DAC_READ_SEARCH / CAP_SYS_ADMIN)
res_handle = libc.syscall(304, -1, 0, 0)
err_handle = ctypes.get_errno()

# 321 = bpf (requires CAP_BPF / CAP_SYS_ADMIN)
res_bpf = libc.syscall(321, 0, 0, 0)
err_bpf = ctypes.get_errno()

print(f"SECCOMP_DIRECT_SYSCALL_TEST: swapon={res_swapon} (errno={err_swapon}), kexec={res_kexec} (errno={err_kexec}), handle={res_handle} (errno={err_handle}), bpf={res_bpf} (errno={err_bpf})")
"""

import subprocess
import os

piston_url = os.getenv("PISTON_URL", "http://127.0.0.1:2000")
try:
    resp_check = httpx.get(f"{piston_url}/api/v2/runtimes", timeout=1.0)
except Exception:
    try:
        wsl_ip = subprocess.check_output(["wsl", "-d", "Ubuntu", "-e", "hostname", "-I"], text=True).split()[0]
        piston_url = f"http://{wsl_ip}:2000"
    except Exception:
        pass

resp = httpx.post(
    f"{piston_url}/api/v2/execute",
    json={
        "language": "python",
        "version": "3.10.0",
        "files": [{"name": "test_seccomp.py", "content": code}]
    },
    timeout=5.0
)

print("HTTP Status:", resp.status_code)
print("Response JSON:")
print(json.dumps(resp.json(), indent=2))

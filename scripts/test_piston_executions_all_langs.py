import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.execution_verifier import ExecutionVerifier
from app.services.piston_health import piston_health_monitor

def main():
    # Force check health sync
    status = piston_health_monitor.check_health_sync()
    print(f"[*] Initial Piston Health Status: {status}")

    ev = ExecutionVerifier(piston_url="http://127.0.0.1:2000", allow_local_fallback=False)

    test_cases = [
        ("python", "print('Hello from Python sandbox!')"),
        ("javascript", "console.log('Hello from JS sandbox!');"),
        ("typescript", "const msg: string = 'Hello from TS sandbox!'; console.log(msg);"),
        ("bash", "echo 'Hello from Bash sandbox!'"),
        ("go", "package main\nimport \"fmt\"\nfunc main() {\n    fmt.Println(\"Hello from Go sandbox!\")\n}\n"),
        ("rust", "fn main() {\n    println!(\"Hello from Rust sandbox!\");\n}\n"),
        ("cpp", "#include <iostream>\nint main() {\n    std::cout << \"Hello from C++ sandbox!\" << std::endl;\n    return 0;\n}\n"),
        ("java", "public class Solution {\n    public static void main(String[] args) {\n        System.out.println(\"Hello from Java sandbox!\");\n    }\n}\n"),
    ]

    all_passed = True
    print("\n--- Running Multi-Language Sandbox Executions ---")
    for lang, code in test_cases:
        res = ev.execute(submitted_code=code, language=lang)
        status_ok = res.get("status") == "success" and res.get("exit_code") == 0
        if not status_ok:
            all_passed = False
        print(f"Language: {lang:12} | Status: {res.get('status'):8} | Exit Code: {res.get('exit_code')} | Time: {res.get('execution_time_ms'):6}ms")
        print(f"  Stdout: {repr(res.get('stdout', '').strip())}")
        if res.get('stderr'):
            print(f"  Stderr: {repr(res.get('stderr', '').strip())}")
        print()

    print("--- Verifying /health Endpoint Data ---")
    final_health = piston_health_monitor.check_health_sync()
    print(f"Final Health State: {final_health}")

    if not all_passed:
        print("[!] Some language executions failed.")
        sys.exit(1)
    else:
        print("[+] All language executions succeeded against Piston sandbox.")

if __name__ == "__main__":
    main()

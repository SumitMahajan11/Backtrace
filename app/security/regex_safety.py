"""Regex safety and ReDoS catastrophic backtracking protection module."""

import os
import re
import multiprocessing
from typing import Optional, Tuple


class ReDoSTimeoutError(TimeoutError):
    """Raised when regex execution exceeds allowed time limit."""
    pass


def _regex_worker(pattern: str, text: str, flags: int, queue: multiprocessing.Queue) -> None:
    """Worker function executing regex search inside a child process."""
    try:
        compiled = re.compile(pattern, flags)
        match = compiled.search(text)
        if match:
            queue.put((match.start(), match.end(), match.group(0)))
        else:
            queue.put(None)
    except Exception as e:
        queue.put(e)


def safe_regex_search(
    pattern: str,
    text: str,
    flags: int = 0,
    timeout_seconds: float = 0.5,
) -> Optional[Tuple[int, int, str]]:
    """
    Executes a regex search against untrusted text inside a process sandbox
    with a strict execution timeout to prevent ReDoS catastrophic backtracking.
    """
    ctx = multiprocessing.get_context("spawn" if os.name == "nt" else "fork")
    queue = ctx.Queue()
    process = ctx.Process(target=_regex_worker, args=(pattern, text, flags, queue))

    process.start()
    process.join(timeout=timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join()
        raise ReDoSTimeoutError(
            f"Regex search timed out after {timeout_seconds}s (ReDoS protection triggered)."
        )

    if not queue.empty():
        result = queue.get()
        if isinstance(result, Exception):
            raise result
        return result

    return None

"""URL and SSRF validation utilities for GitHub repository ingestion."""

import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

from app.models.ingestion import InvalidURLError, SSRFError

# Match https://github.com/owner/repo or https://github.com/owner/repo.git
GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/([a-zA-Z0-9_\-]+)/([a-zA-Z0-9_\-\.]+?)(?:\.git)?/?$"
)


def validate_github_url(url: str) -> tuple[str, str]:
    """
    Validates that a URL is a clean, public GitHub repository URL.
    Returns (owner, repo_name) tuple if valid.
    Raises InvalidURLError if validation fails.
    """
    if not url or not isinstance(url, str):
        raise InvalidURLError("URL must be a non-empty string.")

    parsed = urlparse(url)

    # 1. Scheme check
    if parsed.scheme != "https":
        raise InvalidURLError("Only HTTPS protocol is allowed.")

    # 2. Check for embedded credentials
    if parsed.username or parsed.password:
        raise InvalidURLError("URLs with embedded credentials are explicitly blocked.")

    # 3. Hostname check
    if not parsed.hostname or parsed.hostname.lower() != "github.com":
        raise InvalidURLError("Only public github.com URLs are supported in v1.")

    # 4. Port check (must be default HTTPS 443 or omitted)
    if parsed.port and parsed.port != 443:
        raise InvalidURLError("Non-standard ports are explicitly blocked.")

    # 5. Regex pattern check for owner/repo
    match = GITHUB_URL_PATTERN.match(url.strip())
    if not match:
        raise InvalidURLError("Invalid GitHub repository URL format. Expected: https://github.com/owner/repo")

    owner, repo = match.group(1), match.group(2)

    # Block path traversal attempts in path
    if ".." in owner or ".." in repo:
        raise InvalidURLError("Path traversal patterns detected in repository URL.")

    return owner, repo


def validate_ssrf(hostname: str = "github.com") -> str:
    """
    Resolves hostname IP address and verifies it does not belong to private,
    loopback, link-local, or cloud metadata IP ranges.
    Returns the validated public IP string to enable strict IP pinning.
    Raises SSRFError if blocked.
    """
    try:
        addr_info = socket.getaddrinfo(hostname, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFError(f"Failed to resolve hostname '{hostname}': {e}") from e

    validated_ip = None
    for family, socktype, proto, canonname, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise SSRFError(f"Invalid IP address resolved: {ip_str}")

        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise SSRFError(f"Resolved IP {ip_str} for '{hostname}' is in a restricted private IP range.")
        if not validated_ip:
            validated_ip = ip_str

    if not validated_ip:
        raise SSRFError(f"No valid public IP resolved for hostname '{hostname}'.")

    return validated_ip


def check_repo_reachability(url: str, timeout_seconds: float = 10.0) -> None:
    """
    Executes a lightweight HTTP HEAD/GET request to verify the repository is public and reachable.
    Raises InvalidURLError if the repository returns 404 or fails to reach.
    """
    cleaned_url = url.rstrip("/").removesuffix(".git")
    
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.head(cleaned_url)
            # Some GitHub endpoints return 405 for HEAD, fallback to GET if needed
            if response.status_code == 405:
                response = client.get(cleaned_url, headers={"Range": "bytes=0-10"})

            if response.status_code in (404, 403):
                raise InvalidURLError(
                    f"Repository at '{cleaned_url}' is not publicly reachable (HTTP {response.status_code})."
                )
            elif response.status_code >= 400:
                raise InvalidURLError(
                    f"GitHub returned error HTTP {response.status_code} for repository '{cleaned_url}'."
                )
    except httpx.RequestError as e:
        raise InvalidURLError(f"Failed to reach repository URL: {e}") from e

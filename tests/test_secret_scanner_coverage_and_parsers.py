"""Tests for AST parsing with [REDACTED] placeholders and secret detection coverage."""

import pytest
from app.parser.python_parser import PythonLanguageParser
from app.parser.javascript_parser import JavaScriptLanguageParser
from app.parser.go_parser import GoLanguageParser
from app.parser.rust_parser import RustLanguageParser
from app.security.secret_scanner import SecretScanner


def test_parsers_with_redacted_placeholders():
    """Verifies Python, TS, Go, and Rust real parsers handle [REDACTED] without syntax errors."""
    
    # 1. Python
    py_code = '''
API_KEY = "[REDACTED]"

class AuthService:
    def __init__(self):
        self.token = "[REDACTED]"

    def authenticate(self, user_id: str):
        return True
'''
    py_parser = PythonLanguageParser()
    py_node, py_edges = py_parser.parse_single_file("src/auth.py", py_code, {"src/auth.py"})
    assert py_node.path == "src/auth.py"
    assert "AuthService" in py_node.classes
    assert "authenticate" in py_node.functions

    # 2. TypeScript / JavaScript
    ts_code = '''
export const STRIPE_KEY = "[REDACTED]";

export class PaymentProcessor {
    private secret = "[REDACTED]";

    public processPayment(amount: number): boolean {
        return true;
    }
}

export function initializePayment() {
    return new PaymentProcessor();
}
'''
    js_parser = JavaScriptLanguageParser()
    ts_node, ts_edges = js_parser.parse_single_file("src/payment.ts", ts_code, {"src/payment.ts"})
    assert ts_node.path == "src/payment.ts"
    assert "PaymentProcessor" in ts_node.classes or "PaymentProcessor" in ts_node.exports
    assert "initializePayment" in ts_node.functions or "initializePayment" in ts_node.exports

    # 3. Go
    go_code = '''
package main

import "fmt"

const DatabaseSecret = "[REDACTED]"

type DatabaseConfig struct {
    Password string
}

func ConnectDatabase() bool {
    fmt.Println("Connecting...")
    return true
}

func main() {
    ConnectDatabase()
}
'''
    go_parser = GoLanguageParser()
    go_node, go_edges = go_parser.parse_single_file("cmd/db.go", go_code, {"cmd/db.go"})
    assert go_node.path == "cmd/db.go"
    assert "DatabaseConfig" in go_node.classes or "DatabaseConfig" in go_node.exports
    assert "ConnectDatabase" in go_node.functions

    # 4. Rust
    rust_code = '''
pub const JWT_SECRET: &str = "[REDACTED]";

pub struct TokenManager {
    token: String,
}

impl TokenManager {
    pub fn new() -> Self {
        TokenManager { token: String::from("[REDACTED]") }
    }

    pub fn validate_token(&self) -> bool {
        true
    }
}

pub fn create_manager() -> TokenManager {
    TokenManager::new()
}
'''
    rust_parser = RustLanguageParser()
    rust_node, rust_edges = rust_parser.parse_single_file("src/token.rs", rust_code, {"src/token.rs"})
    assert rust_node.path == "src/token.rs"
    assert "TokenManager" in rust_node.classes or "TokenManager" in rust_node.exports
    assert "create_manager" in rust_node.functions or "validate_token" in rust_node.functions


def test_secret_scanner_detection_coverage():
    """Verifies detection of known secret token formats and variable assignments."""
    scanner = SecretScanner()

    # 1. Google AIza API Key
    google_key = 'GOOGLE_MAPS_KEY = "AIzaSyD-1234567890abcdefghijklmnopqrstuv"'
    red, count = scanner.scan_and_redact(google_key)
    assert count >= 1
    assert "AIzaSyD-" not in red
    assert "[REDACTED]" in red

    # 2. Gemini API Key (AIza...)
    gemini_key = 'GEMINI_API_KEY = "AIzaSyB_1234567890abcdefghijklmnopqrstuv"'
    red, count = scanner.scan_and_redact(gemini_key)
    assert count >= 1
    assert "AIzaSyB_" not in red
    assert "[REDACTED]" in red

    # 3. Tavily API Key (tvly-...)
    tavily_key = 'tavily_api_key = "tvly-abcdef1234567890abcdef1234567890"'
    red, count = scanner.scan_and_redact(tavily_key)
    assert count >= 1
    assert "tvly-abcdef" not in red
    assert "[REDACTED]" in red

    # 4. Stripe sk_live
    dummy_stripe = "sk_" + "live_51AbcDefGhIjKlMnOpQrStUvWxYz1234567890"
    stripe_live = f'stripe_key = "{dummy_stripe}"'
    red, count = scanner.scan_and_redact(stripe_live)
    assert count >= 1
    assert "sk_" + "live_" not in red
    assert "[REDACTED]" in red

    # 5. Stripe whsec (Webhook Secret)
    stripe_webhook = 'endpoint_secret = "whsec_abcdefghijklmnopqrstuvwxyz0123456789"'
    red, count = scanner.scan_and_redact(stripe_webhook)
    assert count >= 1
    assert "whsec_" not in red
    assert "[REDACTED]" in red

    # 6. GitHub Personal Access Token (ghp_...)
    gh_ghp = 'GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB"'
    red, count = scanner.scan_and_redact(gh_ghp)
    assert count >= 1
    assert "ghp_1234567890" not in red
    assert "[REDACTED]" in red

    # 7. GitHub Fine-Grained Token (github_pat_...)
    gh_pat = 'token = "github_pat_11ABCDEF1234567890abcdefghijklmnopqrstuvwxyz_1234567890"'
    red, count = scanner.scan_and_redact(gh_pat)
    assert count >= 1
    assert "github_pat_" not in red
    assert "[REDACTED]" in red

    # 8. AWS AKIA
    aws_akia = 'AWS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"'
    red, count = scanner.scan_and_redact(aws_akia)
    assert count >= 1
    assert "AKIAIOSFODNN7EXAMPLE" not in red
    assert "[REDACTED]" in red

    # 9. JWT Token
    jwt_token = 'user_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"'
    red, count = scanner.scan_and_redact(jwt_token)
    assert count >= 1
    assert "eyJhbGciOi" not in red
    assert "[REDACTED]" in red

    # 10. PEM RSA Private Key Block
    pem_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Y1v4wF4pE2f6jK8n3q7...
-----END RSA PRIVATE KEY-----"""
    red, count = scanner.scan_and_redact(pem_key)
    assert count >= 1
    assert "MIIEowIBAAKCAQEA" not in red
    assert "[REDACTED]" in red


def test_high_entropy_non_secret_variable_is_not_redacted():
    """
    Verifies that high-entropy strings assigned to non-secret variable names
    (such as hashes, binary buffers, GUIDs, and telemetry payloads) are NOT redacted by entropy alone.
    """
    scanner = SecretScanner()

    # MD5 / SHA hash in non-secret variable
    hash_code = 'content_checksum = "d41d8cd98f00b204e9800998ecf8427e"'
    red, count = scanner.scan_and_redact(hash_code)
    assert count == 0
    assert red == hash_code

    # Random hex buffer in non-secret variable
    buffer_code = 'packet_buffer = "8f4b2c1a9e3d7f605a4b3c2d1e0f9a8b7c6d5e4f"'
    red, count = scanner.scan_and_redact(buffer_code)
    assert count == 0
    assert red == buffer_code

    # Natural language description in Field
    field_code = 'field_doc = "Overall confidence tier: VERIFIED, LIKELY_TRUE, CONTRADICTED, INSUFFICIENT_EVIDENCE"'
    red, count = scanner.scan_and_redact(field_code)
    assert count == 0
    assert red == field_code

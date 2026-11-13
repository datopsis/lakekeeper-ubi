"""Deny verification downgrades in the Phase A executable/configuration surface.

This file defines forbidden strings; it is not an executable client. Legacy
smoke/storage tests remain separate regression tests, not Phase A evidence.
"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
FILES = ['tests/tls_profile.py', 'tests/tls_client.py', 'tests/tls_pki.py',
         'scripts/build-tls-proxy.sh', '.tls-fixture/nginx.conf']
FORBIDDEN = [
    r'verify\s*[:=]\s*["\x27]?false', r'--insecure\b', r'curl\s+-[^\s]*k',
    r'CERT_NONE', r'check_hostname\s*=\s*False', r'insecure_?skip_?verify',
    r'danger_accept_invalid_(?:certs|hostnames)', r'AWS_ALLOW_(?:HTTP|INVALID_CERTIFICATES)',
    r'(?:proxy|grpc)_ssl_verify\s+off', r'sslmode\s*[=:]\s*(?:require|allow|prefer|disable|verify-ca)',
    r'_create_unverified_context', r'trust.?all',
]


def check():
    for name in FILES:
        text = (ROOT / name).read_text()
        for pattern in FORBIDDEN:
            assert not re.search(pattern, text, re.I), f'{name}: forbidden TLS setting {pattern}'
    # Inspect the fetched, exact upstream profile as rendered NGINX directives.
    text = (ROOT / '.tls-fixture/nginx.conf').read_text()
    directives = re.findall(r'^\s*(listen|proxy_pass|ssl_protocols|proxy_next_upstream)\s+([^;]+);', text, re.M)
    assert sorted(directives) == sorted([
        ('listen', '8181 ssl default_server'), ('listen', '[::]:8181 ssl default_server'),
        ('proxy_pass', 'http://127.0.0.1:8182'), ('ssl_protocols', 'TLSv1.2 TLSv1.3'),
        ('proxy_next_upstream', 'off')])
    print('TLS PASS static deny scan and parsed proxy profile')


if __name__ == '__main__':
    check()

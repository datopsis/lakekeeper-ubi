"""Fresh verified client in a separate container; stdlib only, JSON via stdin.

The plaintext action is exclusively a rejection probe. It cannot follow redirects.
Credentials and response bodies go only to the harness's private capture pipe.
"""
import datetime
import hashlib
import hmac
import http.client
import json
import socket
import ssl
import sys
import urllib.parse


def request(options):
    action = options.get('action', 'https')
    host = options.get('host', 'catalog')
    port = options.get('port', 8181)
    if action == 'tcp':
        try:
            with socket.create_connection((host, port), timeout=3):
                return {'open': True}
        except ConnectionRefusedError:
            return {'open': False, 'reason': 'refused'}
    method, path = options.get('method', 'GET'), options.get('path', '/health')
    body = options.get('body', '').encode()
    headers = options.get('headers', {})
    if 'credentials' in options:
        access, secret, token = options['credentials']
        now = datetime.datetime.now(datetime.timezone.utc)
        stamp, date = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
        digest = hashlib.sha256(body).hexdigest()
        headers.update({'host': f'{host}:{port}', 'x-amz-date': stamp,
                        'x-amz-content-sha256': digest})
        if token:
            headers['x-amz-security-token'] = token
        names = sorted(headers)
        signed = ';'.join(names)
        target = urllib.parse.urlsplit(path)
        canonical = '\n'.join([method, target.path, target.query,
                               ''.join(f'{k}:{headers[k]}\n' for k in names), signed, digest])
        service = options.get('service', 's3')
        scope = f'{date}/us-east-1/{service}/aws4_request'
        message = '\n'.join(['AWS4-HMAC-SHA256', stamp, scope,
                             hashlib.sha256(canonical.encode()).hexdigest()])
        key = ('AWS4' + secret).encode()
        for component in (date, 'us-east-1', service, 'aws4_request'):
            key = hmac.new(key, component.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
        headers['authorization'] = (f'AWS4-HMAC-SHA256 Credential={access}/{scope}, '
                                    f'SignedHeaders={signed}, Signature={signature}')
    if action == 'plaintext':
        connection = http.client.HTTPConnection(host, port, timeout=5)
    else:
        assert action == 'https'
        context = ssl.create_default_context(cafile=options.get('ca', '/trust/trusted.crt'))
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        connection = http.client.HTTPSConnection(host, port, context=context, timeout=40)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return {'status': response.status, 'body': response.read().decode(),
                'headers': dict(response.getheaders())}
    finally:
        connection.close()


if __name__ == '__main__':
    try:
        print(json.dumps(request(json.load(sys.stdin))))
    except (ssl.SSLCertVerificationError, ConnectionError, http.client.HTTPException) as error:
        print(json.dumps({'error': type(error).__name__, 'detail': str(error)}))

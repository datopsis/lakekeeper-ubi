"""Phase A item 4: exercise the shipped Lakekeeper on native Docker runners.

No container runtime is used by importing this module. Raw diagnostics stay in
a temporary 0700 runner directory; only allowlisted evidence is retained.
"""
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from tls_pki import generate

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ('docker.io/library/python:3.13-slim@sha256:'
          'e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90')
SEAWEED = ('ghcr.io/chrislusf/seaweedfs:4.53_large_disk@sha256:'
           'c272ca3b913a8d9f8f843d42553874f70d41ae0611a1bf8e28d80a7da72d7d51')
TLS_ERRORS = {
    'wrong-ca': r'UnknownIssuer|unknown issuer|certificate verify failed|unable to get local issuer',
    'wrong-root': r'UnknownIssuer|unknown issuer|certificate verify failed|unable to get local issuer',
    'missing-ca': r'UnknownIssuer|unknown issuer|No such file|not found',
    'malformed-ca': r'UnknownIssuer|unknown issuer|no certificates|certificate.*PEM|invalid.*certificate',
    'wrong-san': r'NotValidForName|not valid for name|hostname mismatch|not valid for.*postgres',
    'expired': r'Expired|expired',
}


def pg_url(password, host='postgres', ca='trusted', pool='write'):
    value = f'postgresql://lakekeeper:{password}@{host}:5432/lakekeeper?' + urlencode({
        'sslmode': 'verify-full', 'sslrootcert': f'/trust/{ca}.crt',
        'application_name': f'tls-{pool}'})
    validate_pg_url(value)
    return value


def validate_pg_url(value):
    parsed = urlsplit(value)
    options = parse_qs(parsed.query)
    assert parsed.scheme == 'postgresql' and parsed.port == 5432
    assert options['sslmode'] == ['verify-full']
    assert len(options['sslrootcert']) == 1 and options['sslrootcert'][0].startswith('/trust/')
    assert set(options) == {'sslmode', 'sslrootcert', 'application_name'}


def listeners(text):
    result = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[3] != '0A':
            continue
        address, port = fields[1].split(':')
        raw = bytes.fromhex(address)
        raw = b''.join(raw[n:n + 4][::-1] for n in range(0, len(raw), 4))
        result.append((str(ipaddress.ip_address(raw)), int(port, 16)))
    return sorted(result)


def check_returned_urls(value):
    if isinstance(value, dict):
        for item in value.values():
            check_returned_urls(item)
    elif isinstance(value, list):
        for item in value:
            check_returned_urls(item)
    elif isinstance(value, str):
        assert not value.lower().startswith('http:'), 'server returned a plaintext HTTP URL'


class Qualification:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.prefix = 'lk-tls-' + secrets.token_hex(5)
        self.network = self.prefix + '-net'
        self.containers = set()
        self.volumes = set()
        self.password, self.admin, self.encryption = [secrets.token_hex(24) for _ in range(3)]
        self.access, self.secret, self.signing = [secrets.token_hex(24) for _ in range(3)]
        self.private_values = [self.password, self.admin, self.encryption, self.access,
                               self.secret, self.signing]
        self.image = os.environ['IMAGE']
        self.pg = 'localhost/postgresql-lakekeeper-ubi:development'
        self.proxy = 'localhost/nginx-ubi:tls'
        self.report = {'complete': False, 'architecture': platform.machine(),
                       'revision': os.environ.get('GITHUB_SHA', 'local'), 'assertions': []}

    def command(self, *args, check=True, data=None, timeout=120):
        result = subprocess.run(list(map(str, args)), input=data, capture_output=True,
                                text=True, timeout=timeout)
        if check and result.returncode:
            self.diagnostic(result.stdout + result.stderr)
            raise RuntimeError(f'{args[0]} failed with exit {result.returncode}; private diagnostics retained locally')
        return result

    def docker(self, *args, **kwargs):
        return self.command('docker', *args, **kwargs)

    def diagnostic(self, message):
        for secret in self.private_values:
            message = message.replace(secret, '[REDACTED]')
        with (self.directory / 'diagnostics.log').open('a') as stream:
            stream.write(message + '\n')

    def record(self, name, **evidence):
        self.report['assertions'].append({'name': name, 'result': 'PASS', **evidence})
        print('TLS PASS ' + name + ': ' + json.dumps(evidence), flush=True)

    def name(self, role):
        return self.prefix + '-' + role

    def remove(self, role):
        name = self.name(role)
        if name in self.containers:
            log = self.logs(role)
            leaked = any(secret in log for secret in self.private_values)
            self.docker('rm', '-f', name)
            self.containers.remove(name)
            assert not leaked, role + ': secret in logs'

    def start(self, role, image, command, options=(), env=None, uid=999):
        self.remove(role)
        args = ['run', '-d', '--name', self.name(role), '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--user', f'{uid}:0']
        args += list(options)
        for key, value in (env or {}).items():
            args += ['--env', f'{key}={value}']
        self.containers.add(self.name(role))
        self.docker(*args, image, *command)

    def mount(self, source, target):
        return ['--mount', f'type=bind,src={source},dst={target},readonly']

    def logs(self, role):
        result = self.docker('logs', self.name(role))
        text = result.stdout + result.stderr
        self.diagnostic(text)
        return text

    def wait(self, condition, label, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(1)
        raise AssertionError(f'{label}: readiness timeout (not a TLS rejection)')

    def client(self, **options):
        value = self.docker('exec', '-i', self.name('client'), 'python', '/probe/tls_client.py',
                            data=json.dumps(options))
        return json.loads(value.stdout)

    def loopback_client(self, **options):
        value = self.docker('run', '--rm', '-i', '--network', 'container:' + self.name('catalog'),
                            '--user', '999:0', '--read-only', '--cap-drop', 'ALL',
                            '--security-opt', 'no-new-privileges:true',
                            *self.mount(ROOT / 'tests/tls_client.py', '/probe/tls_client.py'),
                            PYTHON, 'python', '/probe/tls_client.py', data=json.dumps(options))
        return json.loads(value.stdout)

    def api(self, method, path, body=None, expected=200, **options):
        response = self.client(method=method, path=path, body=json.dumps(body) if body else '',
                               headers={'content-type': 'application/json',
                                        'X-Iceberg-Access-Delegation': 'client-managed'}, **options)
        if response.get('status') != expected:
            self.diagnostic(json.dumps(response))
            raise AssertionError(f'{method} {path}: expected {expected}, got {response.get("status", response.get("error"))}')
        assert not any(key.lower() == 'location' for key in response['headers']), 'unexpected redirect'
        value = json.loads(response['body']) if response['body'] else None
        check_returned_urls(value)
        return value

    def sql(self, statement):
        return self.docker('exec', '-i', self.name('postgres'), 'psql', '-XqAt',
                           '-v', 'ON_ERROR_STOP=1', '-h', '/tmp', '-U', 'postgres',
                           '-d', 'lakekeeper', data=statement).stdout.strip()

    def start_pg(self, leaf='valid'):
        path = self.directory / leaf
        self.start('postgres', self.pg, [], [
            '--network', self.network, '--network-alias', 'postgres', '--network-alias', 'alias',
            '--volume', self.name('pg-data') + ':/var/lib/pgsql',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
            *self.mount(path, '/run/tls'), *self.mount(self.directory / 'pg-secrets', '/run/secrets')], {
                'POSTGRES_DB': 'lakekeeper', 'POSTGRES_USER': 'postgres',
                'POSTGRES_PASSWORD_FILE': '/run/secrets/postgres-password',
                'POSTGRESQL_TLS_CERT_FILE': '/run/tls/server.crt',
                'POSTGRESQL_TLS_KEY_FILE': '/run/tls/server.key'}, uid=26)
        self.wait(lambda: self.docker('exec', self.name('postgres'), 'pg_isready', '-h',
                                     '127.0.0.1', check=False).returncode == 0, 'PostgreSQL')

    def environment(self, write=None, read=None):
        env = {'LAKEKEEPER__PG_DATABASE_URL_WRITE': write or pg_url(self.password),
               'LAKEKEEPER__PG_ENCRYPTION_KEY': self.encryption,
               'LAKEKEEPER__BIND_IP': '127.0.0.1', 'LAKEKEEPER__LISTEN_PORT': '8182',
               'LAKEKEEPER__METRICS_PORT': '9000', 'LAKEKEEPER__BASE_URI': 'https://catalog:8181',
               'LAKEKEEPER__PG_READ_POOL_CONNECTIONS': '2',
               'LAKEKEEPER__PG_WRITE_POOL_CONNECTIONS': '2',
               'SSL_CERT_FILE': '/trust/trusted.crt',
               'RUST_LOG': 'info,aws_smithy_http_client=debug'}
        if read is not None:
            env['LAKEKEEPER__PG_DATABASE_URL_READ'] = read
        return env

    def lakekeeper(self, mode='serve', env=None):
        env = env or self.environment()
        for key in ('LAKEKEEPER__PG_DATABASE_URL_WRITE', 'LAKEKEEPER__PG_DATABASE_URL_READ'):
            if key in env:
                validate_pg_url(env[key])
        assert env['LAKEKEEPER__BIND_IP'] == '127.0.0.1'
        assert env['LAKEKEEPER__BASE_URI'] == 'https://catalog:8181'
        assert not any('OPENID' in key or key == 'LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY' for key in env)
        self.remove('proxy')
        self.start('catalog', self.image, [mode], [
            '--network', self.network, '--network-alias', 'catalog',
            *self.mount(self.directory / 'client', '/trust')], env)

    def exited(self):
        return self.docker('inspect', '-f', '{{.State.Running}}', self.name('catalog')).stdout.strip() == 'false'

    def migration(self, env=None):
        self.lakekeeper('migrate', env)
        self.wait(self.exited, 'migration exit')
        assert self.docker('inspect', '-f', '{{.State.ExitCode}}', self.name('catalog')).stdout.strip() == '0'
        self.remove('catalog')

    def serving(self, env=None):
        self.lakekeeper(env=env)
        self.wait(lambda: self.docker('exec', self.name('catalog'), 'lakekeeper', 'healthcheck', '-s',
                                     check=False).returncode == 0, 'catalog')
        self.start_proxy()
        self.wait(lambda: self.client().get('status') == 200, 'verified HTTPS proxy')
        info = self.api('GET', '/management/v1/info')
        assert info['lakekeeper-version'] == json.loads((ROOT / 'artifacts/lakekeeper.lock.json').read_text())['upstreamVersion']

    def start_proxy(self, leaf='catalog'):
        self.start('proxy', self.proxy, ['-c', '/profile/nginx.conf', '-g', 'daemon off;'], [
            '--network', 'container:' + self.name('catalog'),
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
            *self.mount(ROOT / '.tls-fixture/nginx.conf', '/profile/nginx.conf'),
            *self.mount(self.directory / leaf, '/etc/nginx/tls')], uid=10001)
        self.wait(lambda: self.client(action='tcp').get('open'), 'proxy listener')

    def pg_control(self, mode, env=None):
        if mode == 'migrate':
            self.migration(env)
        else:
            self.serving(env)
            rows = self.sql("SELECT application_name || '|' || ssl || '|' || version "
                            "FROM pg_stat_activity JOIN pg_stat_ssl USING(pid) "
                            "WHERE usename='lakekeeper' ORDER BY 1;").splitlines()
            assert rows and all(re.fullmatch(r'tls-(read|write)\|true\|TLSv1\.[23]', row) for row in rows), rows
            self.record('serve-encrypted-pools', connections=rows)

    def pg_negative(self, name, mode, env):
        self.lakekeeper(mode, env)
        self.wait(self.exited, name + ' fail-closed exit')
        code = int(self.docker('inspect', '-f', '{{.State.ExitCode}}', self.name('catalog')).stdout)
        assert code != 0
        log = self.logs('catalog')
        oracle = TLS_ERRORS[name]
        assert re.search(oracle, log, re.I), f'{name}: absent TLS-specific diagnostic'
        assert 'no encryption' not in self.logs('postgres'), 'unexpected plaintext fallback attempt'
        self.record('postgres-' + mode + '-' + name, exit=code, oracle=oracle)

    def pg_matrix(self):
        self.migration()
        self.record('postgres-migrate-verified-TLS')
        for mode in ('migrate', 'serve'):
            for case, ca in [('wrong-ca', 'unrelated'), ('missing-ca', 'missing'),
                             ('malformed-ca', 'malformed')]:
                # Serve exercises each selected pool independently. Read never overrides write.
                for pool in (('write', 'read') if mode == 'serve' else ('write',)):
                    self.pg_control(mode)
                    env = self.environment(read=pg_url(self.password, pool='read'))
                    env['LAKEKEEPER__PG_DATABASE_URL_' + pool.upper()] = pg_url(self.password, ca=ca, pool=pool)
                    self.pg_negative(case, mode, env)
                    self.pg_control(mode)
                    self.record(f'postgres-{mode}-{pool}-{case}-sandwich')
            for leaf in ('wrong-root', 'wrong-san', 'expired'):
                self.pg_control(mode)
                self.remove('proxy')
                self.remove('catalog')
                self.start_pg(leaf)
                self.pg_negative(leaf, mode, self.environment())
                self.start_pg()
                self.pg_control(mode)
        # URL READ takes precedence for reads; omission falls back to WRITE.
        env = self.environment(read=pg_url(self.password, pool='read'))
        self.pg_control('serve', env)
        labels = self.sql("SELECT DISTINCT application_name FROM pg_stat_activity WHERE usename='lakekeeper' ORDER BY 1;")
        assert labels.splitlines() == ['tls-read', 'tls-write']
        self.record('read-URL-over-write-for-reader', application_names=labels.splitlines())
        self.pg_control('serve')
        assert self.sql("SELECT DISTINCT application_name FROM pg_stat_activity WHERE usename='lakekeeper';") == 'tls-write'
        self.record('missing-read-URL-falls-back-to-write')
        env['LAKEKEEPER__PG_DATABASE_URL_READ'] = pg_url(self.password, ca='unrelated', pool='read')
        self.migration(env)
        self.record('migration-uses-write-ignores-read', read_url='wrong CA', write_url='trusted CA')
        # Valid URLs override unreachable individual host/port settings.
        env = self.environment()
        env.update(LAKEKEEPER__PG_HOST_W='unreachable.invalid', LAKEKEEPER__PG_PORT='1')
        self.pg_control('serve', env)
        self.record('URLs-override-separate-host-fields')
        env['LAKEKEEPER__PG_SSL_ROOT_CERT'] = '/trust/unrelated.crt'
        self.pg_negative('wrong-ca', 'serve', env)
        self.pg_control('serve')
        self.record('separate-root-cert-overrides-URL-root-cert')
        self.url_mode_precedence()
        self.plaintext_pg_rejection()

    def url_mode_precedence(self):
        # Deliberately conflicting *negative* input: the verify-full URL must
        # still reject the trusted certificate's wrong SAN despite this field.
        for mode in ('migrate', 'serve'):
            self.pg_control(mode)
            env = self.environment(write=pg_url(self.password, host='alias'))
            env['LAKEKEEPER__PG_SSL_MODE'] = 'disable'
            self.pg_negative('wrong-san', mode, env)
            self.pg_control(mode)
            self.record(mode + '-URL-verify-full-overrides-separate-SSL-mode')

    def plaintext_pg_rejection(self):
        # Explicit negative probe only. No ordinary PG client selects this mode.
        result = self.docker('run', '--rm', '--network', self.network, '--user', '26:0',
                             '--read-only', '--cap-drop', 'ALL',
                             '--security-opt', 'no-new-privileges:true',
                             '--env', 'PGSSLMODE=disable', '--env', 'PGPASSWORD=' + self.password,
                             self.pg, 'psql', '-XwAt', '-h', 'postgres', '-U', 'lakekeeper',
                             '-d', 'lakekeeper', '-c', 'SELECT 1', check=False)
        assert result.returncode != 0 and re.search(r'no pg_hba.conf entry.*no encryption', result.stderr)
        self.record('postgres-plaintext-cannot-authenticate-or-query', exit=result.returncode)

    def inventory(self, role):
        return listeners(self.docker('exec', self.name(role), 'cat', '/proc/net/tcp', '/proc/net/tcp6').stdout)

    def hardening(self, role):
        obj = json.loads(self.docker('inspect', self.name(role)).stdout)[0]
        assert obj['HostConfig']['ReadonlyRootfs']
        assert obj['HostConfig']['CapDrop'] == ['ALL']
        assert 'no-new-privileges:true' in obj['HostConfig']['SecurityOpt']
        assert obj['Config']['User'].split(':')[0] not in ('', '0', 'root')
        status = self.docker('exec', self.name(role), 'cat', '/proc/1/status').stdout
        assert re.search(r'^Uid:\s+[1-9]\d*\s+[1-9]\d*\s+[1-9]\d*\s+[1-9]\d*$', status, re.M)
        assert re.search(r'^CapEff:\s+0000000000000000$', status, re.M)
        assert re.search(r'^NoNewPrivs:\s+1$', status, re.M)
        if role == 'catalog':
            assert all(not mount['RW'] for mount in obj['Mounts'])
            assert not any('OPENID' in item or 'REQUIRE_ENCRYPTION_KEY=' in item for item in obj['Config']['Env'])
            env = dict(item.split('=', 1) for item in obj['Config']['Env'])
            assert env['LAKEKEEPER__BIND_IP'] == '127.0.0.1'
            assert env['LAKEKEEPER__LISTEN_PORT'] == '8182'
            assert env['LAKEKEEPER__METRICS_PORT'] == '9000'
            for key in ('LAKEKEEPER__PG_DATABASE_URL_READ', 'LAKEKEEPER__PG_DATABASE_URL_WRITE'):
                if key in env:
                    validate_pg_url(env[key])
        self.record(role + '-hardened')

    def ingress(self):
        self.serving()
        expected = [('0.0.0.0', 8181), ('127.0.0.1', 8182), ('127.0.0.1', 9000), ('::', 8181)]
        # Docker's embedded resolver is runtime-owned, bound only to 127.0.0.11.
        sockets = self.inventory('catalog')
        application = [s for s in sockets if s[0] != '127.0.0.11']
        assert application == sorted(expected), sockets
        self.record('listener-inventory', sockets=sockets, application_sockets=application)
        for role in ('catalog', 'proxy', 'postgres', 'client'):
            self.hardening(role)
        for port in (8182, 9000, 8080, 8443):
            assert self.client(action='tcp', port=port) == {'open': False, 'reason': 'refused'}
        self.api('GET', '/health')
        self.record('peer-cannot-reach-backend-metrics-or-default-ports')
        metrics = self.loopback_client(action='plaintext', host='127.0.0.1', port=9000, path='/metrics')
        assert metrics['status'] == 200 and 'lakekeeper' in metrics['body']
        for port in (8182, 9000):
            assert self.loopback_client(action='tcp', host='::1', port=port) == {'open': False, 'reason': 'refused'}
        ipv6 = self.loopback_client(action='plaintext', host='::1', port=8181)
        assert ipv6['status'] == 400 and 'plain HTTP request was sent to HTTPS port' in ipv6['body']
        self.record('metrics-loopback-works-and-IPv6-cannot-bypass-TLS')
        for method, path, body in [('GET', '/health', ''), ('POST', '/management/v1/bootstrap',
                                                          '{"accept-terms-of-use":true}')]:
            reply = self.client(action='plaintext', method=method, path=path, body=body)
            assert reply.get('status') == 400 and 'plain HTTP request was sent to HTTPS port' in reply['body']
        self.record('ingress-plaintext-rejected-without-redirect')
        wrong = self.client(ca='/trust/unrelated.crt')
        assert wrong.get('error') == 'SSLCertVerificationError'
        self.api('GET', '/health')
        self.record('ingress-verifies-custom-CA')
        for version in ('TLSv1_2', 'TLSv1_3'):
            reply = self.client(tls_version=version)
            assert reply['status'] == 200 and reply['tls'] == version.replace('_', '.')
            assert json.loads(reply['body'])['health'] == 'ok'
            self.record('ingress-' + reply['tls'], health='ok')
        for case in ('wrong-root', 'wrong-san', 'expired'):
            self.api('GET', '/health')
            self.start_proxy('catalog-' + case)
            reply = self.client()
            assert reply.get('error') == 'SSLCertVerificationError'
            assert re.search(TLS_ERRORS[case], reply['detail'], re.I), reply['detail']
            self.record('ingress-' + case, error=reply['error'])
            self.start_proxy()
            self.api('GET', '/health')
        assert self.docker('exec', self.name('catalog'), 'sh', '-c',
                           'test ! -e /etc/nginx/tls/server.key').returncode == 0
        assert self.docker('exec', self.name('proxy'), 'sh', '-c',
                           'test ! -e /trust/trusted.crt && test ! -e /run/secrets/postgres-password').returncode == 0
        proxy = json.loads(self.docker('inspect', self.name('proxy')).stdout)[0]
        assert not any('LAKEKEEPER' in v for v in proxy['Config']['Env'])
        catalog_id = json.loads(self.docker('inspect', self.name('catalog')).stdout)[0]['Id']
        assert proxy['HostConfig']['NetworkMode'] in ('container:' + self.name('catalog'), 'container:' + catalog_id)
        assert self.docker('exec', self.name('catalog'), 'readlink', '/proc/self/ns/net').stdout == self.docker('exec', self.name('proxy'), 'readlink', '/proc/self/ns/net').stdout
        self.record('shared-network-separate-secret-mounts')
        assert self.docker('exec', self.name('catalog'), 'cat', '/proc/1/comm').stdout.strip() == 'lakekeeper'
        # The unchanged smoke suite tests all key-guard branches; repeat the
        # default missing-key refusal within the hardened TLS fixture as well.
        missing = self.docker('run', '--rm', '--network', 'none', '--read-only',
                              '--user', '999:0', '--cap-drop', 'ALL', '--security-opt',
                              'no-new-privileges:true', self.image, 'serve', check=False)
        assert missing.returncode == 78 and 'LAKEKEEPER__PG_ENCRYPTION_KEY' in missing.stderr
        self.record('encryption-key-default-guard-and-login-policy-unchanged', missing_key_exit=78)

    def start_s3(self, leaf='s3-valid'):
        # Broad V(2) logs access-key mappings. Limit diagnostics to the STS
        # handler, whose caller/role/session-name log contains no credentials.
        self.start('s3', SEAWEED, ['-vmodule=s3api_sts=2', 's3', '-filer=127.0.0.1:8888',
                                  '-ip.bind=0.0.0.0', '-port=8333', '-port.iceberg=0', '-port.lance=0',
                                  '-config=/config/s3.json', '-iam.config=/config/iam.json',
                                  '-iam.readOnly=true', '-cert.file=/run/tls/server.crt',
                                  '-key.file=/run/tls/server.key'], [
            '--network', 'container:' + self.name('weed'),
            '--entrypoint', '/usr/bin/weed',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
            *self.mount(self.directory / leaf, '/run/tls'),
            *self.mount(self.directory / 's3-config', '/config')], uid=1000)
        self.wait(lambda: self.client(action='tcp', host='s3', port=8333).get('open'), 'S3 listener')

    def storage_setup(self):
        role = 'arn:aws:iam::000000000000:role/lakekeeper-vended'
        config = self.directory / 's3-config'
        config.mkdir()
        (config / 's3.json').write_text(json.dumps({'identities': [{
            'name': 'vendor', 'credentials': [{'accessKey': self.access, 'secretKey': self.secret}],
            'actions': ['Admin', 'Read', 'Write', 'List', 'Tagging']}]}))
        (config / 'iam.json').write_text(json.dumps({
            'sts': {'tokenDuration': '1h', 'maxSessionLength': '12h',
                    'issuer': 'lakekeeper-tls-test', 'signingKey': self.signing},
            'policy': {'defaultEffect': 'Deny', 'storeType': 'memory'},
            'policies': [{'name': 'warehouse', 'document': {'Version': '2012-10-17', 'Statement': [{
                'Effect': 'Allow', 'Action': ['s3:*'],
                'Resource': ['arn:aws:s3:::warehouse', 'arn:aws:s3:::warehouse/*']}]}}],
            'roles': [{'roleName': 'lakekeeper-vended', 'roleArn': role,
                       'attachedPolicies': ['warehouse'], 'trustPolicy': {'Version': '2012-10-17',
                           'Statement': [{'Effect': 'Allow', 'Action': ['sts:AssumeRole'],
                               'Principal': {'AWS': 'arn:aws:iam::000000000000:user/vendor'}}]}}]}))
        self.protect(config)
        self.start('weed', SEAWEED, ['server', '-ip=127.0.0.1', '-ip.bind=127.0.0.1',
                                    '-dir=/data', '-filer', '-volume.max=4',
                                    '-master.volumeSizeLimitMB=64'], [
            '--network', self.network, '--network-alias', 's3', '--entrypoint', '/usr/bin/weed',
            '--tmpfs', '/data:rw,noexec,nosuid,nodev,size=512m,uid=1000,gid=0,mode=0700',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777'], uid=1000)
        self.wait(lambda: ('127.0.0.1', 8888) in self.inventory('weed'), 'Seaweed filer')
        self.start_s3()
        # Register a real bucket over verified HTTPS and authenticated SigV4.
        self.wait(lambda: self.client(host='s3', port=8333, method='PUT', path='/warehouse',
                                      credentials=[self.access, self.secret, None]).get('status') == 200,
                  'S3 bucket provisioning')
        self.api('POST', '/management/v1/bootstrap', {'accept-terms-of-use': True}, expected=204)
        warehouse = self.api('POST', '/management/v1/warehouse', {
            'warehouse-name': 'tls-qualification', 'storage-profile': {
                'type': 's3', 'bucket': 'warehouse', 'region': 'us-east-1', 'flavor': 's3-compat',
                'endpoint': 'https://s3:8333', 'sts-endpoint': 'https://s3:8333',
                'sts-enabled': True, 'sts-role-arn': role, 'path-style-access': True},
            'storage-credential': {'type': 's3', 'credential-type': 'access-key',
                                   'access-key-id': self.access, 'secret-access-key': self.secret}}, expected=201)
        self.catalog_path = '/catalog/v1/' + warehouse['warehouse-id']
        stored_profile = self.api('GET', '/management/v1/warehouse/' + warehouse['warehouse-id'])['storage-profile']
        assert stored_profile['endpoint'].rstrip('/') == 'https://s3:8333'
        assert stored_profile['sts-endpoint'].rstrip('/') == 'https://s3:8333'
        assert stored_profile['sts-enabled'] is True
        self.record('runtime-storage-profile-uses-HTTPS-for-S3-and-STS')
        self.api('POST', self.catalog_path + '/namespaces', {'namespace': ['tls']})
        table = self.api('POST', self.catalog_path + '/namespaces/tls/tables', {
            'name': 'probe', 'schema': {'type': 'struct', 'schema-id': 0,
                'fields': [{'id': 1, 'name': 'id', 'required': True, 'type': 'long'}]}})
        self.table_path = self.catalog_path + '/namespaces/tls/tables/probe'
        self.metadata_path = urlsplit(table['metadata-location']).path
        assert table['metadata-location'].startswith('s3://warehouse/')
        self.hardening('weed')
        self.hardening('s3')
        self.record('S3-real-warehouse-and-metadata-write-over-HTTPS', image=SEAWEED)

    def storage_operation(self, edge):
        if edge == 'sts':
            return self.client(path=self.table_path + '/credentials',
                               headers={'X-Iceberg-Access-Delegation': 'vended-credentials'})
        # A load-table response can be served from PostgreSQL alone. Creating a
        # unique table forces a real S3 PutObject in Lakekeeper, without vending.
        self.operation_name = 'write-' + secrets.token_hex(6)
        body = {'name': self.operation_name, 'schema': {'type': 'struct', 'schema-id': 0,
                'fields': [{'id': 1, 'name': 'id', 'required': True, 'type': 'long'}]}}
        return self.client(method='POST', path=self.catalog_path + '/namespaces/tls/tables',
                           body=json.dumps(body), headers={'content-type': 'application/json',
                               'X-Iceberg-Access-Delegation': 'client-managed'})

    def storage_control(self, edge):
        self.serving()
        response = self.storage_operation(edge)
        self.diagnostic(json.dumps(response) if response.get('status') != 200 else 'storage control OK')
        assert response.get('status') == 200, edge + ' control failed'
        value = json.loads(response['body'])
        check_returned_urls(value)
        if edge == 's3':
            assert value['metadata']['schemas'][0]['fields'][0]['name'] == 'id'
            location = value['metadata-location']
            assert location.startswith('s3://warehouse/')
            stored = self.client(host='s3', port=8333, path='/warehouse' + urlsplit(location).path,
                                 credentials=[self.access, self.secret, None])
            assert stored.get('status') == 200
            assert json.loads(stored['body'])['schemas'][0]['fields'][0]['name'] == 'id'
            # Unregister without purge, then register from object storage: the
            # latter forces Lakekeeper itself to GET and parse the metadata.
            self.api('DELETE', self.catalog_path + '/namespaces/tls/tables/' + self.operation_name,
                     expected=204)
            registered = self.api('POST', self.catalog_path + '/namespaces/tls/register',
                                  {'name': self.operation_name, 'metadata-location': location})
            assert registered['metadata']['schemas'][0]['fields'][0]['name'] == 'id'
        else:
            credentials = value['storage-credentials'][0]['config']
            access = credentials['s3.access-key-id']
            secret = credentials['s3.secret-access-key']
            token = credentials['s3.session-token']
            assert all((access, secret, token)) and access != self.access
            self.private_values.extend([access, secret, token])
            assert 'AssumeRole: caller identity=vendor' in self.logs('s3')
            response = self.client(host='s3', port=8333, path='/warehouse' + self.metadata_path,
                                   credentials=[access, secret, token])
            assert response.get('status') == 200, 'issued STS credentials cannot read actual metadata'
            assert json.loads(response['body'])['schemas'][0]['fields'][0]['name'] == 'id'
        self.record(edge + '-verified-control', fresh_process=True)

    def storage_matrix(self):
        for edge in ('s3', 'sts'):
            for case in ('missing-ca', 'wrong-ca', 'wrong-root', 'wrong-san', 'expired'):
                self.storage_control(edge)
                if case in ('wrong-root', 'wrong-san', 'expired'):
                    self.start_s3('s3-' + case)
                env = self.environment()
                if case == 'missing-ca':
                    del env['SSL_CERT_FILE']
                elif case == 'wrong-ca':
                    env['SSL_CERT_FILE'] = '/trust/unrelated.crt'
                self.serving(env)
                reply = self.storage_operation(edge)
                assert reply.get('status', 0) >= 400, edge + ' accepted ' + case
                diagnostic = json.dumps(reply) + self.logs('catalog')
                self.diagnostic(json.dumps(reply))
                oracle = TLS_ERRORS[case]
                assert re.search(oracle, diagnostic, re.I), edge + ': missing TLS-specific rejection'
                assert 's3.session-token' not in reply['body'] and 'AccessKeyId' not in reply['body']
                self.record(edge + '-' + case, status=reply['status'], oracle=oracle, fresh_process=True)
                if case in ('wrong-root', 'wrong-san', 'expired'):
                    self.start_s3()
                self.storage_control(edge)
        for method, path, body in [('GET', '/warehouse', ''),
                                  ('POST', '/', 'Action=AssumeRole&Version=2011-06-15')]:
            reply = self.client(action='plaintext', host='s3', port=8333,
                                method=method, path=path, body=body)
            assert reply.get('status') == 400 and 'HTTP request to an HTTPS server' in reply['body']
        self.record('S3-and-STS-plaintext-rejected')

    def protect(self, directory):
        for path in directory.rglob('*'):
            if path.is_dir():
                path.chmod(0o750)
            elif path.is_file():
                path.chmod(0o440)
                self.command('sudo', 'chown', '0:0', path)
        directory.chmod(0o750)
        self.command('sudo', 'chgrp', '-R', '0', directory)

    def setup(self):
        self.report['certificates'] = generate(self.directory / 'pki')
        # Only individual role directories are mounted, never the PKI parent.
        for path in (self.directory / 'pki').iterdir():
            if path.is_dir() and path.name != 'authority':
                shutil.move(path, self.directory / path.name)
        for name in ('valid', 'wrong-root', 'wrong-san', 'expired', 'catalog',
                     'catalog-wrong-root', 'catalog-wrong-san', 'catalog-expired',
                     's3-valid', 's3-wrong-root', 's3-wrong-san', 's3-expired', 'client'):
            self.protect(self.directory / name)
        config = self.directory / 'pg-secrets'
        config.mkdir()
        (config / 'postgres-password').write_text(self.admin)
        (config / 'lakekeeper-password').write_text(self.password)
        self.protect(config)
        self.docker('network', 'create', self.network)
        self.volumes.add(self.name('pg-data'))
        self.docker('volume', 'create', self.name('pg-data'))
        for image in (PYTHON, SEAWEED):
            self.docker('pull', image, timeout=240)
        architecture = {'x86_64': 'amd64', 'aarch64': 'arm64'}[platform.machine()]
        images = {}
        for image in (self.image, self.pg, self.proxy, SEAWEED, PYTHON):
            item = json.loads(self.docker('image', 'inspect', image).stdout)[0]
            assert item['Architecture'] == architecture
            images[image] = {'id': item['Id'], 'architecture': item['Architecture'],
                             'revision': (item['Config'].get('Labels') or {}).get('org.opencontainers.image.revision'),
                             'lock_sha256': (item['Config'].get('Labels') or {}).get('io.datopsis.artifact-lock.sha256')}
        self.report['images'] = images
        self.start('client', PYTHON, ['python', '-c', 'import time; time.sleep(3600)'], [
            '--network', self.network, *self.mount(ROOT / 'tests/tls_client.py', '/probe/tls_client.py'),
            *self.mount(self.directory / 'client', '/trust')])
        self.start_pg()
        self.sql((ROOT / 'examples/postgres-init.sql').read_text())
        assert self.sql("SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension WHERE extname <> 'plpgsql';") == 'btree_gin,btree_gist,pg_trgm,pgcrypto,uuid-ossp'
        assert self.sql("SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls) FROM pg_roles WHERE rolname='lakekeeper';") == 't'
        assert self.sql("SELECT pg_get_userbyid(datdba) = 'lakekeeper' FROM pg_database WHERE datname='lakekeeper';") == 't'
        assert self.sql("SELECT count(*) FROM pg_auth_members JOIN pg_roles ON member=pg_roles.oid WHERE rolname='lakekeeper';") == '0'
        assert self.sql("SELECT bool_and(pg_get_userbyid(extowner) = 'postgres') FROM pg_extension WHERE extname <> 'plpgsql';") == 't'
        assert self.sql("SELECT string_agg(type, ',' ORDER BY rule_number) FROM pg_hba_file_rules;") == 'local,hostssl,hostssl'
        self.record('postgres-TLS-only-HBA-and-restricted-role')

    def cleanup(self):
        errors = []
        leak = False
        for name in list(self.containers):
            result = self.docker('logs', name, check=False)
            log = result.stdout + result.stderr
            self.diagnostic(log)
            leak |= any(secret in log for secret in self.private_values)
            leak |= bool(re.search(r'BEGIN .*PRIVATE KEY', log))
        for name in list(self.containers):
            errors.append(self.docker('rm', '-f', name, check=False).returncode)
        for volume in self.volumes:
            errors.append(self.docker('volume', 'rm', volume, check=False).returncode)
        errors.append(self.docker('network', 'rm', self.network, check=False).returncode)
        assert not any(errors), 'TLS fixture cleanup failed'
        assert not leak, 'secret in container logs'


def main():
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='lakekeeper-tls-') as directory:
        run = Qualification(directory)
        try:
            run.setup()
            run.pg_matrix()
            run.ingress()
            run.storage_setup()
            run.storage_matrix()
            run.report['complete'] = True
        except Exception:
            # Fixture errors are synthetic. Emit only error/certificate lines,
            # after exact secret redaction; never dump env, config, bodies or PEM.
            for name in list(run.containers):
                logs = run.docker('logs', name, check=False)
                for line in (logs.stdout + logs.stderr).splitlines()[-30:]:
                    if re.search(r'error|failed|fatal|certificate|UnknownIssuer|NotValidForName', line, re.I):
                        for secret in run.private_values:
                            line = line.replace(secret, '[REDACTED]')
                        if not re.search(r'BEGIN .*PRIVATE KEY|session.token|secret.access', line, re.I):
                            print(f'{name}: {line[:2000]}', flush=True)
            raise
        finally:
            try:
                run.cleanup()
            except Exception:
                run.report['complete'] = False
                raise
            finally:
                # Public certificates and allowlisted results only. No logs/configs/keys.
                report = json.dumps(run.report, indent=2) + '\n'
                assert not any(secret in report for secret in run.private_values)
                (ROOT / 'tls-report.json').write_text(report)
                if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
                    with open(summary, 'a') as stream:
                        stream.write(f'### TLS qualification ({run.report["architecture"]})\n\n')
                        for row in run.report['assertions']:
                            stream.write(f'- PASS `{row["name"]}`\n')
                        stream.write(f'\nComplete: {run.report["complete"]}\n')


if __name__ == '__main__':
    main()

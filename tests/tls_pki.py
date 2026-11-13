"""Throwaway RSA PKI; OpenSSL CLI only, signing keys never leave the runner."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import secrets
import shutil
import subprocess


def openssl(*args):
    result = subprocess.run(['openssl', *map(str, args)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('OpenSSL fixture generation/verification failed')
    return result.stdout.strip()


def generate(directory):
    os.umask(0o077)
    directory = Path(directory).resolve()
    authority = directory / 'authority'
    authority.mkdir(parents=True)
    now = datetime.now(timezone.utc)

    def stamp(hours=0, minutes=0):
        return (now + timedelta(hours=hours, minutes=minutes)).strftime('%Y%m%d%H%M%SZ')

    def request(stem, cn):
        openssl('req', '-new', '-newkey', 'rsa:3072', '-nodes', '-sha256',
                '-subj', f'/CN={cn}', '-keyout', stem.with_suffix('.key'),
                '-out', stem.with_suffix('.csr'))

    for root in ('trusted', 'unrelated'):
        stem = authority / root
        request(stem, f'{root} ephemeral test CA')
        (authority / f'{root}.index').touch()
        (authority / f'{root}.serial').write_text(secrets.token_hex(16) + '\n')
        config = authority / f'{root}.cnf'
        config.write_text(f'''[ca]
default_ca = issuer
[issuer]
database = {authority}/{root}.index
serial = {authority}/{root}.serial
new_certs_dir = {authority}
certificate = {stem}.crt
private_key = {stem}.key
default_md = sha256
policy = subject
unique_subject = no
[subject]
commonName = supplied
[root]
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
''')
        openssl('ca', '-batch', '-selfsign', '-config', config, '-extensions', 'root',
                '-startdate', stamp(minutes=-5), '-enddate', stamp(hours=24),
                '-in', stem.with_suffix('.csr'), '-out', stem.with_suffix('.crt'), '-notext')

    inventory = {root: openssl('x509', '-in', authority / f'{root}.crt', '-noout',
                               '-fingerprint', '-sha256', '-serial', '-dates', '-subject')
                 for root in ('trusted', 'unrelated')}
    cases = [('valid', 'trusted', 'postgres', 'postgres', -5, 6),
             ('rotated', 'trusted', 'postgres', 'postgres', -5, 6),
             ('wrong-root', 'unrelated', 'postgres', 'postgres', -5, 6),
             ('wrong-san', 'trusted', 'postgres', 'wrong.invalid', -5, 6),
             ('other-service', 'trusted', 'catalog', 'catalog', -5, 6),
             ('expired', 'trusted', 'postgres', 'postgres', -120, -1),
             ('catalog', 'trusted', 'catalog', 'catalog', -5, 6)]
    cases += [(f's3-{name}', root, 's3', san, start, end)
              for name, root, san, start, end in (
                  ('valid', 'trusted', 's3', -5, 6),
                  ('wrong-root', 'unrelated', 's3', -5, 6),
                  ('wrong-san', 'trusted', 'wrong.invalid', -5, 6),
                  ('expired', 'trusted', 's3', -120, -1))]
    cases += [(f'catalog-{name}', root, 'catalog', san, start, end)
              for name, root, san, start, end in (
                  ('wrong-root', 'unrelated', 'catalog', -5, 6),
                  ('wrong-san', 'trusted', 'wrong.invalid', -5, 6),
                  ('expired', 'trusted', 'catalog', -120, -1))]
    for name, root, cn, san, start_minutes, end_hours in cases:
        target = directory / name
        target.mkdir()
        stem = target / 'server'
        if name in ('wrong-root', 'wrong-san', 'expired', 'future'):
            # Keep the positive key/subject constant; mutate only the target property.
            shutil.copyfile(directory / 'valid/server.key', stem.with_suffix('.key'))
            openssl('req', '-new', '-sha256', '-subj', f'/CN={cn}',
                    '-key', stem.with_suffix('.key'), '-out', stem.with_suffix('.csr'))
        else:
            request(stem, cn)
        extensions = authority / 'leaf.ext'
        extensions.write_text(f'''basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:{san}
''')
        openssl('ca', '-batch', '-rand_serial', '-config', authority / f'{root}.cnf',
                '-extfile', extensions, '-startdate', stamp(minutes=start_minutes),
                '-enddate', stamp(hours=end_hours), '-in', stem.with_suffix('.csr'),
                '-out', stem.with_suffix('.crt'), '-notext')
        stem.with_suffix('.csr').unlink()
        inventory[name] = openssl('x509', '-in', stem.with_suffix('.crt'), '-noout',
                                  '-fingerprint', '-sha256', '-serial', '-dates',
                                  '-subject', '-issuer', '-ext', 'subjectAltName')
        if name in ('valid', 'rotated'):
            openssl('x509', '-in', stem.with_suffix('.crt'), '-checkend', '7200', '-noout')
            openssl('verify', '-CAfile', authority / 'trusted.crt',
                    '-purpose', 'sslserver', '-verify_hostname', 'postgres',
                    stem.with_suffix('.crt'))
    client = directory / 'client'
    client.mkdir()
    for root in ('trusted', 'unrelated'):
        (client / f'{root}.crt').write_bytes((authority / f'{root}.crt').read_bytes())
    (client / 'malformed.crt').write_text('not a certificate\n')
    # Remove authority keys before any container is created or material is staged.
    for key in authority.glob('*.key'):
        key.unlink()
    return inventory

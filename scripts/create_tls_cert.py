#!/usr/bin/env python3
"""Create a local self-signed CA and an HTTPS certificate. No proxy, Serve or Funnel."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    return subprocess.run(command, check=True, capture_output=True, text=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ip',action='append',default=[],help='Additional IP in certificate SAN; repeat as needed')
    parser.add_argument('--dns-name',action='append',default=[],help='Additional DNS name in SAN')
    parser.add_argument('--renew',action='store_true',help='Reissue leaf certificate using the same local CA')
    args=parser.parse_args()
    ips={'127.0.0.1',*args.ip}
    if not args.ip and shutil.which('tailscale'):
        result=subprocess.run(['tailscale','ip','-4'],capture_output=True,text=True)
        if result.returncode==0: ips.update(result.stdout.split())
    for ip in ips: ipaddress.ip_address(ip)
    dns={'localhost',*args.dns_name}
    for name in dns:
        if not name or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for ch in name):
            raise ValueError('Invalid DNS name')
    folder=ROOT/'certs'; folder.mkdir(exist_ok=True,mode=0o700); folder.chmod(0o700)
    ca,key=folder/'ca.pem',folder/'ca-key.pem'
    certificate,server_key=folder/'server.pem',folder/'server-key.pem'
    previous_umask=os.umask(0o077)
    try:
        if ca.exists()!=key.exists(): raise RuntimeError('Incomplete local CA; restore its certificate/key pair')
        if not ca.exists():
            run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-sha256','-days','3650',
                '-keyout',str(key),'-out',str(ca),'-subj','/CN=Zonos Local CA',
                '-addext','basicConstraints=critical,CA:TRUE',
                '-addext','keyUsage=critical,keyCertSign,cRLSign')
        if not certificate.exists() or not server_key.exists() or args.renew:
            with tempfile.TemporaryDirectory(prefix='zonos-cert-') as temporary:
                csr=Path(temporary)/'server.csr'; extensions=Path(temporary)/'extensions.cnf'
                san=','.join(['IP:'+ip for ip in sorted(ips)]+['DNS:'+name for name in sorted(dns)])
                extensions.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName='+san+'\n')
                run('openssl','req','-new','-newkey','rsa:2048','-nodes','-sha256',
                    '-keyout',str(server_key),'-out',str(csr),'-subj','/CN=Zonos Local API')
                run('openssl','x509','-req','-in',str(csr),'-CA',str(ca),'-CAkey',str(key),
                    '-CAcreateserial','-out',str(certificate),'-days','365','-sha256','-extfile',str(extensions))
        for ip in ips:
            if subprocess.run(['openssl','x509','-in',str(certificate),'-noout','-checkip',ip],capture_output=True).returncode:
                raise RuntimeError('Certificate does not cover requested IP; re-run with --renew')
        for name in dns:
            if subprocess.run(['openssl','x509','-in',str(certificate),'-noout','-checkhost',name],capture_output=True).returncode:
                raise RuntimeError('Certificate does not cover requested DNS name; re-run with --renew')
        for file in [key,ca,server_key,certificate]: file.chmod(0o600)
        # Only the public CA certificate is downloadable; private keys stay outside frontend/.
        shutil.copyfile(ca,ROOT/'frontend/ca.crt'); (ROOT/'frontend/ca.crt').chmod(0o644)
        (ROOT/'frontend/tls.json').write_text(json.dumps({'https_port':1920,'ca_certificate':'/ca.crt'})+'\n')
        (ROOT/'frontend/tls.json').chmod(0o644)
    finally: os.umask(previous_umask)
    print('Local HTTPS certificate ready. Import the public /ca.crt into the client trust store.')
    print(run('openssl','x509','-in',str(ca),'-noout','-fingerprint','-sha256').stdout.strip())


if __name__=='__main__':
    try: main()
    except (OSError,RuntimeError,ValueError,subprocess.CalledProcessError) as error: sys.exit(str(error))

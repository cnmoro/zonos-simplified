"""Opt-in native HTTPS verification with the locally trusted CA."""
import json
import os
from pathlib import Path
import ssl
import socket
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('ZONOS_HTTPS_URL'), 'Set ZONOS_HTTPS_URL for native TLS tests')
class NativeHTTPS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.https=os.environ['ZONOS_HTTPS_URL'].rstrip('/')
        cls.http=os.environ.get('ZONOS_LIVE_URL','http://127.0.0.1:1919').rstrip('/')
        cls.ca=Path(os.environ.get('ZONOS_CA_FILE',str(ROOT/'certs/ca.pem')))
        cls.context=ssl.create_default_context(cafile=str(cls.ca))

    @unittest.skipUnless(os.environ.get('ZONOS_EXPECT_HTTP_DISABLED') == '1', 'Set ZONOS_EXPECT_HTTP_DISABLED=1 to assert HTTP is closed')
    def test_plain_http_port_is_closed(self):
        host = urlparse(self.https).hostname
        with socket.socket() as connection:
            connection.settimeout(2)
            self.assertNotEqual(connection.connect_ex((host,1919)),0)

    def test_verified_tls_health_and_same_library(self):
        with urllib.request.urlopen(self.https+'/v2/health',context=self.context) as response:
            self.assertEqual(json.load(response)['status'],'ok')
        with urllib.request.urlopen(self.https+'/v2/voices',context=self.context) as response:
            via_https=json.load(response)
        with urllib.request.urlopen(self.http+'/v2/voices') as response:
            self.assertEqual(via_https,json.load(response))

    def test_only_public_ca_is_downloadable(self):
        with urllib.request.urlopen(self.http+'/ca.crt') as response:
            self.assertEqual(response.read(),self.ca.read_bytes())
        for path in ['/ca-key.pem','/server-key.pem','/certs/server-key.pem','/%2e%2e/certs/ca-key.pem']:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.https+path,context=self.context)
            self.assertEqual(error.exception.code,404)

    def test_advertised_https_port_matches_listener(self):
        with urllib.request.urlopen(self.http+'/tls.json') as response:
            config=json.load(response)
        self.assertEqual(config['https_port'],urlparse(self.https).port)
        self.assertEqual(config['ca_certificate'],'/ca.crt')


if __name__=='__main__': unittest.main()

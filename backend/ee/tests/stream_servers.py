"""Local collectors for the audit-streaming tests: HTTP, syslog over TCP/TLS/UDP.

Each runs in a thread on 127.0.0.1 and an ephemeral port, and records what
it received, so the tests check the bytes on the wire, not a mock.
"""
import datetime
import http.server
import os
import socket
import socketserver
import ssl
import tempfile
import threading


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get('Content-Length') or 0)
        self.server.requests.append({'path': self.path, 'headers': dict(self.headers),
                                     'body': self.rfile.read(length)})
        code = self.server.status_codes.pop(0) if self.server.status_codes else 200
        self.send_response(code)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, *args):
        pass


class HttpCollector:
    """tls=True: HTTPS with a self-signed certificate for localhost (``cert_pem``)."""

    def __init__(self, tls=False):
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self.server.requests = []
        self.server.status_codes = []
        self.tls = tls
        self.cert_pem = None
        if tls:
            self.cert_pem, key_pem = self_signed()
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            with tempfile.TemporaryDirectory() as tmp:
                cert_file, key_file = os.path.join(tmp, 'c.pem'), os.path.join(tmp, 'k.pem')
                with open(cert_file, 'w') as f:
                    f.write(self.cert_pem)
                with open(key_file, 'w') as f:
                    f.write(key_pem)
                context.load_cert_chain(cert_file, key_file)
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        if self.tls:
            return f'https://localhost:{self.server.server_address[1]}/ingest'
        return f'http://127.0.0.1:{self.server.server_address[1]}/ingest'

    @property
    def requests(self):
        return self.server.requests

    def answer(self, *codes):
        self.server.status_codes.extend(codes)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def parse_octet_counted(data):
    """RFC 5425 frames "LEN SP MSG" back to messages."""
    messages = []
    while data:
        length, _, rest = data.partition(b' ')
        n = int(length)
        messages.append(rest[:n])
        data = rest[n:]
    return messages


class _TcpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        chunks = []
        while True:
            try:
                chunk = self.request.recv(65536)
            except (ssl.SSLError, ConnectionError):
                break  # a TLS peer that closed without close_notify
            if not chunk:
                break
            chunks.append(chunk)
        self.server.received.extend(parse_octet_counted(b''.join(chunks)))


class _TcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, tls_context=None):
        super().__init__(('127.0.0.1', 0), _TcpHandler)
        self.received = []
        self.tls_context = tls_context

    def get_request(self):
        sock, addr = super().get_request()
        if self.tls_context:
            sock = self.tls_context.wrap_socket(sock, server_side=True)
        return sock, addr


def self_signed(common_name='localhost'):
    """(certificate PEM, key PEM) for localhost and 127.0.0.1."""
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(common_name),
                                                        x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),
                           critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()).decode())


class SyslogCollector:
    """transport: 'tcp', 'tls' or 'udp'."""

    def __init__(self, transport='tcp'):
        self.transport = transport
        self.cert_pem = None
        if transport == 'udp':
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(('127.0.0.1', 0))
            self.sock.settimeout(5)
            self.port = self.sock.getsockname()[1]
            self._udp = []
            return
        context = None
        if transport == 'tls':
            self.cert_pem, key_pem = self_signed()
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            with tempfile.TemporaryDirectory() as tmp:
                cert_file, key_file = os.path.join(tmp, 'c.pem'), os.path.join(tmp, 'k.pem')
                with open(cert_file, 'w') as f:
                    f.write(self.cert_pem)
                with open(key_file, 'w') as f:
                    f.write(key_pem)
                context.load_cert_chain(cert_file, key_file)
        self.server = _TcpServer(context)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def messages(self, expected=1, timeout=5):
        if self.transport == 'udp':
            while len(self._udp) < expected:
                self._udp.append(self.sock.recv(65536))
            return self._udp
        import time
        deadline = time.time() + timeout
        while len(self.server.received) < expected and time.time() < deadline:
            time.sleep(0.02)
        return self.server.received

    def close(self):
        if self.transport == 'udp':
            self.sock.close()
        else:
            self.server.shutdown()
            self.server.server_close()

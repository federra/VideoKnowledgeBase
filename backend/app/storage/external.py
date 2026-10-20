"""Allowlisted HTTPS only, validated DNS answers pinned at the actual TCP connection."""

import http.client
import ipaddress
import os
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from threading import BoundedSemaphore, Timer
from urllib.parse import urljoin, urlsplit

from app.security.errors import Denied

DNS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cip-dns")
DNS_SLOTS = BoundedSemaphore(2)


def dns(host, port, *, timeout=5, **kwargs):
    deadline = time.monotonic() + timeout
    if not DNS_SLOTS.acquire(timeout=min(1, timeout)):
        raise Denied("FETCH_FAILED")
    future = DNS_POOL.submit(socket.getaddrinfo, host, port, **kwargs)
    future.add_done_callback(lambda done: DNS_SLOTS.release())
    try:
        return future.result(timeout=max(0.001, deadline - time.monotonic()))
    except (TimeoutError, OSError) as exc:
        raise Denied("FETCH_FAILED") from exc


@dataclass(frozen=True)
class Target:
    host: str
    ip: str
    path: str


def resolve_url(url, allowed, *, resolver=dns, timeout=5):
    try:
        if len(url) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in url):
            raise ValueError()
        parts = urlsplit(url)
        host = parts.hostname
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or parts.fragment
            or not host
            or host not in allowed
            or parts.port not in (None, 443)
            or not re.fullmatch(r"[a-zA-Z0-9]+(?:[.-][a-zA-Z0-9]+)*", host)
        ):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise Denied("UNSAFE_URL")
        addresses = resolver(host, 443, type=socket.SOCK_STREAM, timeout=timeout)
        if not addresses:
            raise ValueError()
        ips = []
        for entry in addresses:
            addr = ipaddress.ip_address(entry[4][0])
            if (
                not addr.is_global
                or addr.is_multicast
                or addr.is_reserved
                or getattr(addr, "ipv4_mapped", None)
                or getattr(addr, "sixtofour", None)
                or getattr(addr, "teredo", None)
            ):
                raise ValueError()
            ips.append(str(addr))
        return Target(
            host, ips[0], (parts.path or "/") + ("?" + parts.query if parts.query else "")
        )
    except (ValueError, OSError) as exc:
        raise Denied("UNSAFE_URL") from exc


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, target, timeout):
        super().__init__(target.host, 443, timeout=timeout, context=ssl.create_default_context())
        self.target = target
        self.abort_socket = None

    def connect(self):
        # Numeric address is passed to connect directly: never re-resolve host or use a proxy.
        family = socket.AF_INET6 if ":" in self.target.ip else socket.AF_INET
        raw = socket.socket(family, socket.SOCK_STREAM)
        deadline = time.monotonic() + self.timeout
        try:
            raw.settimeout(self.timeout)
            raw.connect((self.target.ip, 443))
            if ipaddress.ip_address(raw.getpeername()[0]) != ipaddress.ip_address(self.target.ip):
                raise Denied("UNSAFE_URL")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Denied("FETCH_FAILED")
            raw.settimeout(remaining)
            self.sock = self._context.wrap_socket(raw, server_hostname=self.target.host)
            # HTTPConnection may close/clear its socket while HTTPResponse retains a
            # makefile. A plain duplicate FD remains shutdown-capable even if the
            # SSLSocket object has marked itself closed. It never reads TLS bytes.
            self.abort_socket = socket.socket(
                family, socket.SOCK_STREAM, fileno=os.dup(self.sock.fileno())
            )
        except BaseException:
            raw.close()
            raise

    def abort(self):
        guard = self.abort_socket
        if guard is not None:
            try:
                guard.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def release(self):
        try:
            self.close()
        finally:
            if self.abort_socket is not None:
                self.abort_socket.close()
                self.abort_socket = None


def fetch(url, allowed, staged, *, resolver=dns, connector=PinnedHTTPS, total_timeout=20):
    if not 0 < total_timeout <= 20:
        raise ValueError("Invalid external deadline")
    deadline = time.monotonic() + total_timeout
    current = url
    try:
        for hop in range(4):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Denied("FETCH_FAILED")
            target = resolve_url(current, allowed, resolver=resolver, timeout=min(5, remaining))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Denied("FETCH_FAILED")
            connection = connector(target, min(5, remaining))

            def abort(connection=connection):
                if hasattr(connection, "abort"):
                    connection.abort()
                    return
                sock = connection.sock
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

            timer = Timer(remaining, abort)
            timer.daemon = True
            timer.start()
            response = None
            try:
                connection.request(
                    "GET",
                    target.path,
                    headers={
                        "Host": target.host,
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                        "User-Agent": "CIP-File/0.1",
                    },
                )
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location or hop == 3:
                        raise Denied("UNSAFE_URL")
                    current = urljoin(current, location)
                    continue
                if (
                    response.status != 200
                    or response.getheader("Content-Encoding", "identity").lower() != "identity"
                ):
                    raise Denied("FETCH_FAILED")
                length = response.getheader("Content-Length")
                if length and (
                    len(length) > 20 or not length.isdecimal() or int(length) > staged.maximum
                ):
                    raise Denied("FILE_TOO_LARGE")
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise Denied("FETCH_FAILED")
                    if connection.sock:
                        connection.sock.settimeout(min(5, remaining))
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    staged.write(chunk)
                if time.monotonic() >= deadline:
                    raise Denied("FETCH_FAILED")
                if length and staged.size != int(length):
                    raise Denied("FETCH_FAILED")
                return response.getheader("Content-Type", "").split(";")[0].lower(), current
            finally:
                timer.cancel()
                if response is not None:
                    response.close()
                if hasattr(connection, "release"):
                    connection.release()
                else:
                    connection.close()
    except (OSError, http.client.HTTPException) as exc:
        raise Denied("FETCH_FAILED") from exc

"""Bloqueo REAL de red saliente para el proceso Python de la API (prueba T10).

Se activa poniendo este directorio en PYTHONPATH. Cualquier conexión a una dirección que no sea
loopback lanza OSError y se registra en el archivo indicado por UMBRAL_NETBLOCK_LOG, de modo que la
prueba puede demostrar cuántos intentos de conexión externa hubo (y que todos fueron bloqueados).
"""

import ipaddress
import os
import socket

_LOG = os.environ.get("UMBRAL_NETBLOCK_LOG")
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo


def _is_loopback(host) -> bool:
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _record(kind: str, target) -> None:
    if _LOG:
        try:
            with open(_LOG, "a", encoding="utf-8") as fh:
                fh.write(f"{kind}\t{target}\n")
        except OSError:
            pass


def _connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(address, tuple) and not _is_loopback(host):
        _record("connect", address)
        raise OSError(f"[umbral-netblock] conexión externa bloqueada: {address}")
    return _orig_connect(self, address)


def _connect_ex(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(address, tuple) and not _is_loopback(host):
        _record("connect_ex", address)
        return 101  # ENETUNREACH
    return _orig_connect_ex(self, address)


def _getaddrinfo(host, *args, **kwargs):
    if not _is_loopback(host):
        _record("dns", host)
        raise socket.gaierror(-2, f"[umbral-netblock] DNS bloqueado: {host}")
    return _orig_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo

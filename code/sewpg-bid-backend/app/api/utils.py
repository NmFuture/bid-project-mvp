from __future__ import annotations

import ipaddress
import platform
import socket
import subprocess
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.services.minio_client import minio_client


def now_message(message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"message": message}
    if payload is not None:
        data["payload"] = payload
    return data


def absolute_url(request: Request, path: str) -> str:
    return str(request.base_url).rstrip("/") + path


def _preferred_lan_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False

    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False

    if ip in ipaddress.ip_network("198.18.0.0/15") or ip in ipaddress.ip_network("100.64.0.0/10"):
        return False

    return ip_text.startswith("192.168.") or ip_text.startswith("10.") or (
        ip_text.startswith("172.") and 16 <= int(ip_text.split(".")[1]) <= 31
    )


def _darwin_default_interface_ip() -> str:
    try:
        route_output = subprocess.run(
            ["route", "get", "default"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        interface_name = ""
        for line in route_output.splitlines():
            if "interface:" in line:
                interface_name = line.split("interface:", 1)[1].strip()
                break
        if not interface_name:
            return ""

        ip_text = subprocess.run(
            ["ipconfig", "getifaddr", interface_name],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if _preferred_lan_ip(ip_text):
            return ip_text
    except (OSError, subprocess.CalledProcessError):
        return ""

    return ""


@lru_cache(maxsize=1)
def detect_lan_ip() -> str:
    darwin_ip = _darwin_default_interface_ip()
    if darwin_ip:
        return darwin_ip

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            lan_ip = sock.getsockname()[0]
            if _preferred_lan_ip(lan_ip):
                return lan_ip
    except OSError:
        pass

    try:
        _, _, ip_addresses = socket.gethostbyname_ex(socket.gethostname())
        for ip_address in ip_addresses:
            if _preferred_lan_ip(ip_address):
                return ip_address
    except socket.gaierror:
        pass

    return ""


def onlyoffice_backend_base_url(request: Request) -> str:
    if settings.onlyoffice_backend_base_url:
        return settings.onlyoffice_backend_base_url

    host = request.url.hostname or ""
    scheme = request.url.scheme or "http"
    port = request.url.port

    if host in {"127.0.0.1", "localhost"}:
        default_port = 80 if scheme == "http" else 443
        port_suffix = f":{port}" if port and port != default_port else ""
        if platform.system() == "Darwin":
            return f"{scheme}://host.docker.internal{port_suffix}"
        lan_ip = detect_lan_ip()
        if lan_ip:
            return f"{scheme}://{lan_ip}{port_suffix}"

    return str(request.base_url).rstrip("/")


def content_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename)}"


def minio_streaming_response(
    payload: dict[str, Any],
    *,
    default_file_name: str = "download.bin",
    default_media_type: str = "application/octet-stream",
) -> StreamingResponse:
    response = minio_client.get_object_response(payload["bucket"], payload["key"])

    def iterate_chunks():
        try:
            for chunk in response.stream(64 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    file_name = str(payload.get("fileName") or default_file_name)
    media_type = str(payload.get("mimeType") or default_media_type)
    return StreamingResponse(
        iterate_chunks(),
        media_type=media_type,
        headers={"Content-Disposition": content_disposition(file_name)},
    )

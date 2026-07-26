import json
import os
import urllib.parse
from typing import List

from .core import normalize_relative_path


def is_external_resource_uri(uri: str) -> bool:
    parsed = urllib.parse.urlparse(uri)
    return bool(parsed.scheme) and parsed.scheme.lower() not in {"data"}


def sniff_model_format(local_file_path: str) -> str:
    with open(local_file_path, "rb") as f:
        head = f.read(64)
    if len(head) >= 4 and head[:4] == b"glTF":
        return "glb"
    text_head = head.lstrip()
    if text_head.startswith(b"{") or text_head.startswith(b"["):
        return "gltf"
    return "unknown"


def collect_gltf_resource_paths(gltf_file_path: str) -> List[str]:
    with open(gltf_file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    resource_paths: List[str] = []
    for key in ("buffers", "images"):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            uri = item.get("uri")
            if not isinstance(uri, str):
                continue
            stripped = uri.strip()
            if not stripped or stripped.startswith("data:") or is_external_resource_uri(stripped):
                continue
            decoded = urllib.parse.unquote(urllib.parse.urlsplit(stripped).path)
            resource_paths.append(normalize_relative_path(decoded))

    seen = set()
    ordered_paths: List[str] = []
    for resource_path in resource_paths:
        if resource_path in seen:
            continue
        seen.add(resource_path)
        ordered_paths.append(resource_path)
    return ordered_paths

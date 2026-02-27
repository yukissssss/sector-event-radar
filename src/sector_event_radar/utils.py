from __future__ import annotations

import hashlib
import re
import unicodedata


def slugify_ascii(text: str, max_len: int = 64) -> str:
    """ASCIIのみで安全に使えるslugを作る（canonical_keyのsub_type用）。"""
    # NFKDで分解してASCIIへ落とす
    norm = unicodedata.normalize("NFKD", text)
    norm = norm.encode("ascii", "ignore").decode("ascii")
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
    if not norm:
        norm = "event"
    return norm[:max_len].strip("-")


def short_hash(text: str, n: int = 8) -> str:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return h[:n]

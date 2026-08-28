"""密码哈希（§27）：pbkdf2_hmac 存储，客户端传输前先 SHA-256，避免明文。

约定：客户端发送 `sha256(raw_password)`（16 进制）作为 password 字段；
服务端对收到的值做 pbkdf2 后落库，校验时对收到的值再算 pbkdf2 比对。
"""

import hashlib
import hmac
import os

_ITERATIONS = 100_000


def hash_password(client_value: str) -> str:
    """把客户端传来的值（sha256 十六进制）哈希为存储串 `pbkdf2$iter$salt$digest`。"""
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", client_value.encode(), bytes.fromhex(salt), _ITERATIONS).hex()
    return f"pbkdf2${_ITERATIONS}${salt}${digest}"


def verify_password(client_value: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        _, iterations, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac(
            "sha256", client_value.encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc, digest)


def client_sha256(raw_password: str) -> str:
    """前端用于传输的 SHA-256 值（与后端约定）。"""
    return hashlib.sha256(raw_password.encode()).hexdigest()

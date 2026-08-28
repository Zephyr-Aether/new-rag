"""Sandbox（§6.5 / §23.4）：工具执行资源/出口限额。

MVP：输出大小上限（防大 payload 撑爆 Context）+ 出站端口白名单（配合 SSRF 内网拦截）。
真沙箱（子进程/网络隔离）为生产形态。
"""

import json
from dataclasses import dataclass, field


@dataclass
class SandboxConfig:
    max_output_bytes: int = 100_000  # 工具输出序列化大小上限
    allowed_ports: set[int] = field(default_factory=set)  # 空 = 不限端口（SSRF 仍拦截内网）


def serialize_size(data) -> int:
    """工具输出大小估算：字符串按字节，结构体按 JSON 序列化字节。"""
    if data is None:
        return 0
    if isinstance(data, str):
        return len(data.encode("utf-8"))
    if isinstance(data, (dict, list)):
        return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return len(str(data).encode("utf-8"))

"""敏感数据脱敏（§13.3 / §15.3）。

Mask/Redact：日志、Trace、审计、缓存中敏感字段统一脱敏（`sk-****`、`138****1234`）。
脱敏只用于"观测/持久化"，绝不用于真正的 LLM Prompt（模型需要真实数据）。
"""

import re
from typing import Any

# 常见 secret 前缀/格式
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_BEARER_RE = re.compile(r"\bBearer [A-Za-z0-9._~+/=-]{16,}\b", re.I)
_PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\d\b")
# key = value（key 是敏感词）
_KEYVALUE_RE = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|token|password|secret|credential|access[_-]?key)"
    r"[\"']?\s*[:=]\s*)([\"'][^\"']*[\"']|\S+)"
)

PATTERNS: list[tuple[re.Pattern, str]] = [
    (_SK_RE, "sk-****"),
    (_BEARER_RE, "Bearer ****"),
    (_PHONE_RE, "138****1234"),
    (_EMAIL_RE, "***@***"),
    (_CARD_RE, "****-****-****-****"),
]


class Redactor:
    """可插拔脱敏器：`mask(text)` 处理字符串；`mask_object` 递归处理 dict/list。"""

    def mask(self, text: str) -> str:
        text = _KEYVALUE_RE.sub(lambda m: f"{m.group(1)}****", text)
        for pattern, repl in PATTERNS:
            text = pattern.sub(repl, text)
        return text

    def mask_object(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.mask(obj)
        if isinstance(obj, dict):
            return {k: self.mask_object(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.mask_object(v) for v in obj]
        return obj


# 进程内单例（规则无状态）
redactor = Redactor()


def mask(text: str) -> str:
    return redactor.mask(text)


def mask_object(obj: Any) -> Any:
    return redactor.mask_object(obj)

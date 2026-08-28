"""NotificationService（§19）：审批人通知——多通道（log / email / webhook-IM）。

MVP：
- LogNotifier：结构化日志（默认）
- EmailNotifier：SMTP 邮件（transport 可注入供测试）
- WebhookNotifier：IM/webhook POST（企业微信/Slack/DingTalk 等）
配置 APP_APPROVAL_NOTIFY_CHANNELS="log,email,webhook" + smtp/webhook 参数。
"""

import hashlib
import hmac
import json
import logging
import time
from email.message import EmailMessage

import httpx

logger = logging.getLogger("agent-platform.notification")


def _sign_body(secret: str, timestamp: str, body: str) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()


def verify_signature(secret: str, timestamp: str, body: str, signature: str) -> bool:
    """§19 收方校验：X-Agent-Signature=sha256:<hex> 是否由本平台签名。"""
    expected = _sign_body(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)


class LogNotifier:
    async def notify(self, *, tenant_id, approval_id, tool_ref, requester_id="", message="") -> dict:
        msg = message or f"审批请求：{tool_ref}（approval_id={approval_id}）"
        logger.info(
            "approval-notify tenant=%s approval=%s tool=%s requester=%s msg=%s",
            tenant_id,
            approval_id,
            tool_ref,
            requester_id,
            msg,
        )
        return {"channel": "log"}


class WebhookNotifier:
    """IM/webhook 通知（§19）：POST JSON + HMAC 签名（X-Agent-Timestamp / X-Agent-Signature）。"""

    def __init__(self, webhook_url: str, secret: str = "", transport=None):
        self.webhook_url = webhook_url
        self.secret = secret
        self.transport = transport  # 测试注入 MockTransport

    async def notify(self, *, tenant_id, approval_id, tool_ref, requester_id="", message="") -> dict:
        msg = message or f"审批请求：{tool_ref}（approval_id={approval_id}）"
        payload = {"approval_id": approval_id, "tenant_id": tenant_id, "tool_ref": tool_ref, "message": msg}
        body = json.dumps(payload, ensure_ascii=False)
        timestamp = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-Agent-Timestamp": timestamp}
        if self.secret:
            headers["X-Agent-Signature"] = f"sha256={_sign_body(self.secret, timestamp, body)}"
        try:
            async with httpx.AsyncClient(timeout=3.0, transport=self.transport) as c:
                await c.post(self.webhook_url, content=body, headers=headers)
        except Exception as exc:  # noqa: BLE001 通知失败不影响审批主流程
            logger.warning("approval webhook failed: %s", exc)
        return {"channel": "webhook", "signed": bool(self.secret)}


class EmailNotifier:
    """SMTP 邮件（§19 审批人邮件）。transport 可注入 SMTP 兼容对象供测试。"""

    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_addr: str = "agent-platform@local",
        to_addrs: tuple[str, ...] = (),
        transport=None,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self._transport = transport

    async def notify(self, *, tenant_id, approval_id, tool_ref, requester_id="", message="") -> dict:
        msg = EmailMessage()
        msg["Subject"] = f"[审批] {tool_ref} 待审批"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        body = (
            f"审批请求：{tool_ref}\n"
            f"approval_id：{approval_id}\n"
            f"tenant：{tenant_id}\n"
            f"requester：{requester_id}\n"
            f"说明：{message or '-'}\n"
            f"审批地址：/approvals/{approval_id}"
        )
        msg.set_content(body)
        if self._transport is not None:
            smtp = self._transport()
        else:
            import smtplib

            smtp = smtplib.SMTP(self.smtp_host, self.smtp_port)
        with smtp:
            if self.smtp_user:
                smtp.starttls()
                smtp.login(self.smtp_user, self.smtp_password)
            smtp.sendmail(self.from_addr, list(self.to_addrs), msg.as_string())
        return {"channel": "email", "to": self.to_addrs}


class NotificationService:
    def __init__(self, channels: list | None = None):
        self.channels = channels or []

    async def notify(
        self, *, tenant_id: str, approval_id: str, tool_ref: str, requester_id: str = "", message: str = ""
    ) -> dict:
        for ch in self.channels:
            await ch.notify(
                tenant_id=tenant_id,
                approval_id=approval_id,
                tool_ref=tool_ref,
                requester_id=requester_id,
                message=message,
            )
        return {"notified": True, "channels": len(self.channels)}


def make_notification_service(settings) -> NotificationService:
    """按配置组装通道（§19）。"""
    channels: list = []
    for name in (settings.approval_notify_channels or "log").split(","):
        name = name.strip()
        if name == "log":
            channels.append(LogNotifier())
        elif name == "webhook" and settings.approval_webhook_url:
            channels.append(
                WebhookNotifier(settings.approval_webhook_url, secret=settings.approval_webhook_secret)
            )
        elif name == "email" and settings.approval_email_to:
            channels.append(
                EmailNotifier(
                    smtp_host=settings.smtp_host,
                    smtp_port=settings.smtp_port,
                    smtp_user=settings.smtp_user,
                    smtp_password=settings.smtp_password,
                    from_addr=settings.smtp_from,
                    to_addrs=tuple(a.strip() for a in settings.approval_email_to.split(",") if a.strip()),
                )
            )
    return NotificationService(channels)

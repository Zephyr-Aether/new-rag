"""审批通知（§19）：Email/SMTP（transport 可注入）/ Log / 工厂。"""

from app.notification import EmailNotifier, LogNotifier, make_notification_service
from app.settings import Settings


class _FakeSmtp:
    def __init__(self):
        self.sent: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, pwd):
        pass

    def sendmail(self, from_addr, to_addrs, msg):
        self.sent.append((from_addr, to_addrs, msg))


async def test_email_notifier_sends():
    from email import message_from_string

    fake = _FakeSmtp()
    notifier = EmailNotifier(
        smtp_host="smtp.test",
        smtp_user="u",
        smtp_password="p",
        to_addrs=("m@x.com",),
        transport=lambda: fake,
    )
    await notifier.notify(tenant_id="t", approval_id="a1", tool_ref="pay")
    assert fake.sent
    _from, to_addrs, raw = fake.sent[0]
    assert "m@x.com" in to_addrs
    parsed = message_from_string(raw)
    body = parsed.get_payload(decode=True).decode("utf-8", errors="replace")
    assert "pay" in body and "a1" in body  # 邮件正文含工具与审批号


async def test_log_notifier():
    assert (await LogNotifier().notify(tenant_id="t", approval_id="a1", tool_ref="pay"))["channel"] == "log"


async def test_webhook_signature():
    import httpx

    from app.notification import WebhookNotifier, verify_signature

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode()
        return httpx.Response(200)

    notifier = WebhookNotifier(
        "https://im.example/hook", secret="s3cret", transport=httpx.MockTransport(handler)
    )
    await notifier.notify(tenant_id="t", approval_id="a1", tool_ref="pay")
    lower = {k.lower(): v for k, v in captured["headers"].items()}
    assert "x-agent-signature" in lower
    timestamp = lower["x-agent-timestamp"]
    sig = lower["x-agent-signature"].replace("sha256=", "")
    assert verify_signature("s3cret", timestamp, captured["body"], sig) is True
    assert verify_signature("wrong-secret", timestamp, captured["body"], sig) is False


def test_factory_assembles_channels_by_config():
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        llm_provider="mock",
        approval_notify_channels="log,email",
        approval_email_to="m@x.com",
        smtp_host="smtp.test",
    )
    assert len(make_notification_service(settings).channels) == 2
    settings2 = Settings(
        database_url="sqlite+aiosqlite://", llm_provider="mock", approval_notify_channels="log"
    )
    assert len(make_notification_service(settings2).channels) == 1

import responses

from statuspack import discord


def test_is_configured_rejects_placeholder():
    assert discord.is_configured("https://discord.com/api/webhooks/123/abc") is True
    assert discord.is_configured("your_discord_webhook_url_here") is False
    assert discord.is_configured("") is False
    assert discord.is_configured(None) is False


def test_format_alert_uses_status_emoji():
    down = discord.format_alert("svc", "Triggered", "https://x", "detail")
    up = discord.format_alert("svc", "Recovered", "https://x")
    assert down.startswith("🔴")
    assert up.startswith("🟢")


def test_send_alert_skips_when_placeholder():
    res = discord.send_alert(
        "svc", "Triggered", "https://x", webhook_url="your_discord_webhook_url_here"
    )
    assert res.delivered is False
    assert "not configured" in res.reason


@responses.activate
def test_send_alert_delivers_to_real_webhook():
    url = "https://discord.com/api/webhooks/1/token"
    responses.post(url, status=204)
    res = discord.send_alert("svc", "Triggered", "https://x", webhook_url=url)
    assert res.delivered is True
    assert res.status_code == 204

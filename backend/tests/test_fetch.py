import httpx
import pytest

from calendar_io import CalendarError, fetch_ics, require_public_http
from ical_parser import EXAMPLE_1


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/calendar.ics",
        "http://10.1.2.3/calendar.ics",
        "http://192.168.0.8/calendar.ics",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/calendar.ics",
        "file:///tmp/calendar.ics",
        "ftp://example.com/calendar.ics",
    ],
)
def test_rejects_non_public_urls(url):
    with pytest.raises(CalendarError):
        require_public_http(url)


def test_unresolvable_host():
    with pytest.raises(CalendarError, match="resolve"):
        require_public_http("http://this-host-should-not-exist.invalid/feed.ics")


def test_fetch_reads_a_public_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "8.8.8.8"
        return httpx.Response(200, content=EXAMPLE_1.encode())

    text = fetch_ics("http://8.8.8.8/feed.ics", transport=httpx.MockTransport(handler))
    assert "BEGIN:VEVENT" in text


def test_redirect_to_a_private_host_is_refused():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret.ics"})

    with pytest.raises(CalendarError, match="public"):
        fetch_ics("http://8.8.8.8/feed.ics", transport=httpx.MockTransport(handler))
    assert seen == ["http://8.8.8.8/feed.ics"]

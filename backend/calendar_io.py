"""Fetch a calendar feed and turn VEVENTs into stored items."""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from datetime import datetime

import httpx

from ical_parser import COURSE_RE, DEFAULT_TYPE, LOCAL_TZ, TYPE_RULES, _classify, parse_ical
from models import Item

MAX_BYTES = 1_500_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15.0
USER_AGENT = "Desk/1.0 (iCal import)"


class CalendarError(Exception):
    """A feed the user can fix: bad URL, private host, or not iCal."""


def course_from_title(title: str) -> str | None:
    match = COURSE_RE.search(title)
    if not match:
        return None
    return f"{match.group(1)} {match.group(2)}"


def _keyword_matched(title: str, item_type: str) -> bool:
    """True when a type rule matched, including event keywords.

    `_classify` returns event both for a real event keyword and as the fallback.
    """
    if item_type != DEFAULT_TYPE:
        return True
    for type_name, keywords in TYPE_RULES:
        if type_name != DEFAULT_TYPE:
            continue
        for keyword in keywords:
            if re.search(r"\b" + re.escape(keyword) + r"(?:s|es)?\d*\b", title, re.I):
                return True
    return False


def classify_title(title: str) -> dict:
    item_type = _classify(title or "")
    return {
        "type": item_type,
        "locked": item_type == "exam",
        "matched": _keyword_matched(title or "", item_type),
    }


def normalize_instant(value: str) -> str:
    """Store a due time as ISO 8601 in America/Los_Angeles.

    A value without a zone is the student's local wall time.
    """
    text = value.strip()
    if not text:
        raise ValueError("A date and time is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Use an ISO date and time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ).isoformat()


def ensure_ical(raw: str) -> str:
    text = raw.lstrip("\ufeff")
    folded = text.upper()
    if "BEGIN:VCALENDAR" not in folded and "BEGIN:VEVENT" not in folded:
        raise CalendarError(
            "That doesn't look like an iCal feed. Upload a .ics file or paste a calendar URL."
        )
    return text


def items_from_ical(raw: str) -> list[Item]:
    parsed = parse_ical(ensure_ical(raw))
    if len(parsed) > 2000:
        raise CalendarError("That feed has too many events to import at once")
    items: list[Item] = []
    for entry in parsed:
        title = (entry["title"] or "").strip()[:300] or "Untitled deadline"
        item_type = entry["type"] if entry["type"] in {
            "assignment", "quiz", "exam", "event", "personal"
        } else "event"
        items.append(
            Item(
                id=str(entry["id"]),
                title=title,
                course=entry["course"],
                type=item_type,
                due_or_start=entry["due_or_start"],
                source="canvas",
                estimated_effort_hours=None,
                locked=item_type == "exam",
                status="open",
                description=(entry.get("description") or "")[:5000],
            )
        )
    return items


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not ip.is_global


def require_public_http(url: str) -> str:
    """Return the URL if it is http(s) and every resolved address is public."""
    text = url.strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise CalendarError("Feed URL must start with http:// or https://")
    host = parsed.hostname
    if not host:
        raise CalendarError("Feed URL is missing a host")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked(literal):
            raise CalendarError("Feed URL must point at a public address")
        return text
    try:
        infos = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise CalendarError("Could not resolve that host") from exc
    if not infos:
        raise CalendarError("Could not resolve that host")
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if _blocked(address):
            raise CalendarError("Feed URL must point at a public address")
    return text


def fetch_ics(url: str, transport: httpx.BaseTransport | None = None) -> str:
    """GET a calendar feed. Redirect targets are checked the same way as the first URL."""
    current = require_public_http(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/calendar, text/plain, */*"}
    try:
        with httpx.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
        ) as client:
            for hop in range(MAX_REDIRECTS + 1):
                try:
                    with client.stream("GET", current, headers=headers) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise CalendarError(
                                    "The calendar feed redirected without a location"
                                )
                            if hop == MAX_REDIRECTS:
                                raise CalendarError("The calendar feed redirected too many times")
                            current = require_public_http(urllib.parse.urljoin(current, location))
                            continue
                        if response.status_code != 200:
                            raise CalendarError(
                                f"The calendar feed returned status {response.status_code}"
                            )
                        chunks: list[bytes] = []
                        total = 0
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > MAX_BYTES:
                                raise CalendarError("That calendar feed is too large")
                            chunks.append(chunk)
                        return b"".join(chunks).decode("utf-8-sig", errors="replace")
                except CalendarError:
                    raise
                except httpx.TimeoutException as exc:
                    raise CalendarError("The calendar feed timed out") from exc
                except httpx.HTTPError as exc:
                    raise CalendarError("Could not reach that calendar feed") from exc
    except CalendarError:
        raise
    raise CalendarError("Could not reach that calendar feed")

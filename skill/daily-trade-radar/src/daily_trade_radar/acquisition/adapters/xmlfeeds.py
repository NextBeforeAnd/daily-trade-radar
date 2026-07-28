"""Parse supplied RSS, Atom, and sitemap XML without crawling linked pages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from xml.etree import ElementTree


MAX_XML_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class DiscoveryEntry:
    title: str
    url: str
    published_at: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _child_text(element, names: set[str]) -> str | None:
    for child in element:
        if _local(child.tag) in names and child.text and child.text.strip():
            return child.text.strip()
    return None


def _parse_root(content: str):
    if len(content.encode("utf-8")) > MAX_XML_BYTES:
        raise ValueError("XML input exceeds 5 MiB")
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueError(f"invalid XML: {exc}") from exc


def parse_feed(content: str) -> tuple[str, list[DiscoveryEntry]]:
    root = _parse_root(content)
    root_name = _local(root.tag)
    entries: list[DiscoveryEntry] = []
    if root_name == "rss" or any(_local(item.tag) == "channel" for item in root):
        for item in root.iter():
            if _local(item.tag) != "item":
                continue
            url = _child_text(item, {"link"})
            if not url:
                continue
            entries.append(DiscoveryEntry(
                title=_child_text(item, {"title"}) or url,
                url=url,
                published_at=_child_text(item, {"pubdate", "published", "updated"}),
                summary=_child_text(item, {"description", "summary"}),
            ))
        return "rss", entries
    if root_name == "feed":
        for item in root:
            if _local(item.tag) != "entry":
                continue
            url = None
            for child in item:
                if _local(child.tag) == "link" and child.attrib.get("href"):
                    url = child.attrib["href"].strip()
                    if child.attrib.get("rel", "alternate") == "alternate":
                        break
            if not url:
                continue
            entries.append(DiscoveryEntry(
                title=_child_text(item, {"title"}) or url,
                url=url,
                published_at=_child_text(item, {"published", "updated"}),
                summary=_child_text(item, {"summary", "content"}),
            ))
        return "atom", entries
    raise ValueError("XML is neither RSS nor Atom")


def parse_sitemap(content: str) -> list[DiscoveryEntry]:
    root = _parse_root(content)
    if _local(root.tag) not in {"urlset", "sitemapindex"}:
        raise ValueError("XML is not a sitemap")
    entries: list[DiscoveryEntry] = []
    for item in root:
        if _local(item.tag) not in {"url", "sitemap"}:
            continue
        url = _child_text(item, {"loc"})
        if not url:
            continue
        entries.append(DiscoveryEntry(
            title=url,
            url=url,
            published_at=_child_text(item, {"lastmod"}),
        ))
    return entries

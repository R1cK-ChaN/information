"""HTML → Markdown conversion for government report pages."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment
from markdownify import markdownify


def html_to_markdown(html: str) -> str:
    """Convert HTML content to clean markdown.

    Removes scripts, styles, navigation, and other noise elements,
    then converts remaining HTML to markdown via markdownify.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise tags
    for tag in soup.find_all(
        ["script", "style", "nav", "header", "footer", "iframe", "noscript"]
    ):
        tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Remove common noise classes/ids
    for selector in [
        ".breadcrumb", ".pagination", ".social-share", ".sidebar",
        "#sidebar", ".nav", ".menu", ".footer", ".header",
    ]:
        for el in soup.select(selector):
            el.decompose()

    md = markdownify(str(soup), heading_style="ATX", strip=["img"])

    # Collapse excessive whitespace
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r" {2,}", " ", md)

    return md.strip()

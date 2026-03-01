"""Tests for HTML → markdown converter."""

from gov_report.converter import html_to_markdown


def test_basic_conversion():
    html = "<h1>Title</h1><p>Hello world</p>"
    md = html_to_markdown(html)
    assert "# Title" in md
    assert "Hello world" in md


def test_removes_scripts():
    html = "<p>Content</p><script>alert('xss')</script>"
    md = html_to_markdown(html)
    assert "Content" in md
    assert "alert" not in md


def test_removes_nav():
    html = "<nav><a href='/'>Home</a></nav><p>Article body</p>"
    md = html_to_markdown(html)
    assert "Article body" in md
    # nav content should be removed
    assert "Home" not in md


def test_collapses_whitespace():
    html = "<p>Line 1</p>\n\n\n\n\n<p>Line 2</p>"
    md = html_to_markdown(html)
    # Should not have more than 2 consecutive newlines
    assert "\n\n\n" not in md


def test_table_preserved():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    md = html_to_markdown(html)
    assert "A" in md
    assert "1" in md

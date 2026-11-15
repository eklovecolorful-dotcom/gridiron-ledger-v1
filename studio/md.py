"""A small Markdown-subset renderer (stdlib only).

Supports: #..### headings, paragraphs, **bold**, *italic*, `code`, [text](url),
![alt](src), - / 1. lists, > blockquotes, --- rules, ``` fences,
plus [[fact:ID|text]] citations and {own|watched|visited:text} markers.
"""
import html
import re

from .draft import FACT_RE, FIRST_RE, fact_text

SAFE_URL = re.compile(r"^(https?://|mailto:|/|\.{0,2}/|#)", re.I)


def esc(s):
    return html.escape(str(s), quote=True)


def inline(text, facts=None, refs=None):
    facts = facts if facts is not None else {}
    stash = []

    def keep(s):
        stash.append(s)
        return "\x00%d\x00" % (len(stash) - 1)

    def fact_sub(m):
        fid = int(m.group(1))
        shown = esc(fact_text(facts.get(fid), m.group(2)))
        if refs is None:
            return keep(shown)
        if fid not in refs:
            refs.append(fid)
        n = refs.index(fid) + 1
        return keep('%s<sup class="ref"><a href="#src-%d" aria-label="來源 %d">%d</a></sup>' % (shown, n, n, n))

    text = FACT_RE.sub(fact_sub, text)
    text = FIRST_RE.sub(lambda m: m.group(2) or "", text)
    text = re.sub(r"`([^`]+)`", lambda m: keep("<code>%s</code>" % esc(m.group(1))), text)

    def img_sub(m):
        src = m.group(2).strip()
        if not SAFE_URL.match(src):
            return keep(esc(m.group(1)))
        return keep('<img src="%s" alt="%s" loading="lazy">' % (esc(src), esc(m.group(1))))

    def link_sub(m):
        url = m.group(2).strip()
        if not SAFE_URL.match(url):
            return m.group(1)
        ext = ' rel="noopener"' if url.startswith("http") else ""
        return keep('<a href="%s"%s>' % (esc(url), ext)) + m.group(1) + keep("</a>")

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img_sub, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link_sub, text)
    text = esc(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\s][^*]*)\*(?!\*)", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def render(body, facts=None, refs=None):
    lines = body.split("\n")
    out, i = [], 0
    para = []

    def flush():
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para), facts, refs))
            para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append("<pre><code>%s</code></pre>" % esc("\n".join(code)))
        elif not s:
            flush()
        elif re.match(r"^#{1,3}\s", s):
            flush()
            n = len(s) - len(s.lstrip("#"))
            lv = 2 if n <= 2 else 3
            out.append("<h%d>%s</h%d>" % (lv, inline(s[n:].strip(), facts, refs), lv))
        elif re.fullmatch(r"[-*_]{3,}", s):
            flush()
            out.append("<hr>")
        elif s.startswith(">"):
            flush()
            q = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q.append(lines[i].strip()[1:].strip())
                i += 1
            out.append('<blockquote><p>%s</p></blockquote>' % inline(" ".join(q), facts, refs))
            continue
        elif re.match(r"^([-*+]|\d+\.)\s", s):
            flush()
            ordered = bool(re.match(r"^\d+\.", s))
            items = []
            while i < len(lines) and re.match(r"^([-*+]|\d+\.)\s", lines[i].strip()):
                items.append(re.sub(r"^([-*+]|\d+\.)\s+", "", lines[i].strip()))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(x, facts, refs) for x in items), tag))
            continue
        else:
            para.append(s)
        i += 1
    flush()
    return "\n".join(out)

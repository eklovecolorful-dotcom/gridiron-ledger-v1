"""Draft files: front matter, [[fact:ID]] markers and first-hand markers."""
import hashlib
import re
from pathlib import Path

from .core import LedgerError, fmt_num

FACT_RE = re.compile(r"\[\[fact:(\d+)(?:\|([^\]]*))?\]\]")
FIRST_RE = re.compile(r"\{(own|watched|visited)(?::([^{}]*))?\}")
META_ORDER = ["content_id", "title", "summary", "pillar", "game", "date", "status",
              "approved", "approved_sha", "version", "platforms", "sample"]


class Draft:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            raise LedgerError("找不到稿件：%s" % path)
        text = self.path.read_text(encoding="utf-8")
        lines = text.split("\n")
        self.meta = {}
        self.body_line = 1  # 1-based line number in file where body starts
        if lines and lines[0].strip() == "---":
            end = None
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    end = i
                    break
            if end is None:
                raise LedgerError("%s：檔頭沒有結尾的 ---" % path)
            for ln in lines[1:end]:
                if not ln.strip() or ln.lstrip().startswith("#") or ":" not in ln:
                    continue
                k, v = ln.split(":", 1)
                self.meta[k.strip()] = _parse_value(v.strip())
            self.body = "\n".join(lines[end + 1:])
            self.body_line = end + 2
        else:
            self.body = text

    # convenience
    @property
    def content_id(self):
        cid = self.meta.get("content_id")
        if not cid:
            raise LedgerError("%s：檔頭缺 content_id" % self.path)
        return str(cid)

    @property
    def version(self):
        try:
            return int(self.meta.get("version", 1))
        except (TypeError, ValueError):
            return 1

    @property
    def approved(self):
        return self.meta.get("approved") is True

    def body_sha(self):
        return hashlib.sha256(self.body.strip().encode("utf-8")).hexdigest()[:16]

    def fact_ids(self):
        seen = []
        for m in FACT_RE.finditer(self.body):
            i = int(m.group(1))
            if i not in seen:
                seen.append(i)
        return seen

    def custom_text_fact_ids(self):
        """Facts cited with hand-written display text (need manual edit on correction)."""
        return sorted({int(m.group(1)) for m in FACT_RE.finditer(self.body) if m.group(2)})

    def save_meta(self, **updates):
        self.meta.update(updates)
        keys = [k for k in META_ORDER if k in self.meta] + \
               [k for k in self.meta if k not in META_ORDER]
        head = ["---"] + ["%s: %s" % (k, _dump_value(self.meta[k])) for k in keys] + ["---"]
        self.path.write_text("\n".join(head) + "\n" + self.body, encoding="utf-8")
        self.body_line = len(head) + 1


def _parse_value(v):
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v.strip("'\"")


def _dump_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return str(v)


def fact_text(fact, custom=None):
    """Visible text for a fact marker."""
    if custom:
        return custom
    if fact is None:
        return "〔缺 fact〕"
    if fact["number"] is None:
        return fact["claim"]
    unit = fact["unit"] or ""
    sep = "" if (not unit or unit[0] in "%％" or ord(unit[0]) > 0x2E7F) else " "
    return fmt_num(fact["number"]) + sep + unit


def strip_markers(text, facts=None):
    """Plain text: fact markers resolved, first-hand markers removed (wrapped text kept)."""
    facts = facts or {}
    text = FACT_RE.sub(lambda m: fact_text(facts.get(int(m.group(1))), m.group(2)), text)
    return FIRST_RE.sub(lambda m: m.group(2) or "", text)


def load_facts(con, ids=None):
    rows = con.execute("SELECT * FROM facts").fetchall()
    return {r["id"]: r for r in rows if ids is None or r["id"] in ids}


def sections(body):
    """Split body into [(heading, start_index, [lines])] by ## headings; first has heading ''."""
    out = [["", 0, []]]
    for i, ln in enumerate(body.split("\n")):
        m = re.match(r"^#{1,3}\s+(.*)$", ln)
        if m:
            out.append([m.group(1).strip(), i, []])
        else:
            out[-1][2].append(ln)
    return out


def paragraphs(body):
    """Prose paragraphs as (line_index, text); skips headings, quotes, lists, code, rules."""
    out, buf, start, fence = [], [], 0, False
    lines = body.split("\n")
    for i, ln in enumerate(lines + [""]):
        s = ln.strip()
        if s.startswith("```"):
            fence = not fence
            s = ""
        if fence:
            s = ""
        skip = (not s or s.startswith("#") or s.startswith(">") or
                re.match(r"^([-*+]|\d+\.)\s", s) or re.fullmatch(r"[-*_]{3,}", s))
        if skip:
            if buf:
                out.append((start, " ".join(buf)))
                buf = []
        else:
            if not buf:
                start = i
            buf.append(s)
    return out

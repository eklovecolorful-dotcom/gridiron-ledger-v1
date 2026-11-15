"""`ledger check`: fact gate (gate A) + de-AI lint (blueprint 5.3)."""
import json
import math
import re

from .draft import FACT_RE, FIRST_RE, Draft, load_facts, paragraphs, sections, strip_markers

DEFAULT_LINT = {
    "fail_threshold": 1,
    "rewrite_threshold": 3,
    "banned_phrases": [
        "值得注意的是", "總而言之", "深入探討", "全面解析", "賦能", "無縫", "引領", "綜上所述",
        "讓我們一起", "不可或缺", "眾所周知", "無限機遇",
        "delve", "in today's fast-paced", "it's worth noting", "it is worth noting",
        "in conclusion", "game-changer", "seamless", "unlock the power", "ever-evolving",
        "navigate the landscape", "a testament to", "let's dive in",
    ],
    "banned_patterns": [
        {"label": "不僅……更……", "regex": "不僅[^。！？\\n]{0,40}更"},
        {"label": "在……的時代", "regex": "在[^。，！？\\n]{1,14}的時代"},
    ],
    "scaffold_groups": [
        ["首先", "其次", "再者", "最後"],
        ["firstly", "secondly", "thirdly", "lastly"],
    ],
    "opening_chars": 2,
    "min_sentences_for_rhythm": 6,
    "min_sentence_cv": 0.35,
    "first_hand_markers": ["own", "watched", "visited"],
    "change_mind_heading": "(改口|改變看法|change my mind)",
    "change_mind_min_chars": 12,
    "placeholder_tokens": ["【待填"],
    "number_allowlist": ["49ers", "76ers"],
}

NUM_RE = re.compile(r"[0-9０-９]+(?:[.,][0-9０-９]+)*\s?[%％]?")
SENT_SPLIT = re.compile(r"[。！？!?；;]+|\.(?=\s|$)|\n")


def load_lint_config(home):
    cfg = json.loads(json.dumps(DEFAULT_LINT))
    p = home / "50-prompts" / "lint.json"
    if p.exists():
        user = json.loads(p.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
    return cfg


class Report:
    def __init__(self, draft):
        self.draft = draft
        self.issues = []          # (gate, rule, line, message)
        self.rule_status = {}     # rule -> bool passed

    def add(self, gate, rule, line, msg):
        self.issues.append((gate, rule, line, msg))
        self.rule_status[(gate, rule)] = False

    def ok(self, gate, rule):
        self.rule_status.setdefault((gate, rule), True)

    @property
    def fact_fail(self):
        return any(g == "fact" for g, _, _, _ in self.issues)

    @property
    def lint_failed_rules(self):
        return sorted({r for g, r, _, _ in self.issues if g == "lint"})

    def passed(self, cfg=None):
        thr = (cfg or DEFAULT_LINT).get("fail_threshold", 1)
        return not self.fact_fail and len(self.lint_failed_rules) < thr

    def render(self, cfg=None):
        cfg = cfg or DEFAULT_LINT
        d = self.draft
        out = ["檢查報告 Check report — %s  (%s v%s)" % (d.path.name, d.meta.get("content_id", "?"), d.version), ""]
        out.append("閘門 A  數字核對 Fact gate: %s" % ("FAIL 未通過" if self.fact_fail else "PASS 通過"))
        n = 0
        for g, r, line, msg in self.issues:
            if g == "fact":
                n += 1
                out.append("  %2d. 第 %s 行  [%s] %s" % (n, line if line else "-", r, msg))
        failed = self.lint_failed_rules
        out.append("")
        out.append("去 AI 化檢查 De-AI lint: %s（%d 項未過）" % (
            "FAIL 未通過" if len(failed) >= cfg.get("fail_threshold", 1) else "PASS 通過", len(failed)))
        for g, r, line, msg in self.issues:
            if g == "lint":
                n += 1
                out.append("  %2d. 第 %s 行  [%s] %s" % (n, line if line else "-", r, msg))
        if len(failed) >= cfg.get("rewrite_threshold", 3):
            out.append("  → 有 %d 項沒過，依藍圖 5.3：退回重寫。" % len(failed))
        out.append("")
        out.append("需要你親自確認（腳本查不出來）Manual checks:")
        out.append("  - 大聲唸一遍，像翻譯的地方改掉；專有名詞第一次出現附英文。")
        out.append("  - 每個論點有沒有配一個數字、人名或地點。")
        out.append("  - 中文數字（例如「六年」）腳本不檢查，請自己核對來源。")
        out.append("")
        out.append("結果 RESULT: %s" % ("PASS 可送核准" if self.passed(cfg) else "FAIL 請修正後重跑"))
        return "\n".join(out)


def _mask(line, allow, placeholders=()):
    """Blank out spans whose digits are legitimately not 'body numbers'."""
    for tok in placeholders:
        line = re.sub(re.escape(tok) + r"[^】]*】?", " ", line)
    line = re.sub(r"`[^`]*`", " ", line)
    line = re.sub(r"\]\([^)]*\)", "] ", line)          # link targets
    line = re.sub(r"https?://\S+", " ", line)
    line = FACT_RE.sub(" ", line)
    line = re.sub(r"\{(?:own|watched|visited):[^{}]*\}", " ", line)
    line = re.sub(r"^\s*\d+\.\s", " ", line)            # ordered-list prefix
    for tok in allow:
        line = re.sub(re.escape(tok), " ", line, flags=re.I)
    return line


def check_draft(home, path, con=None):
    cfg = load_lint_config(home)
    d = Draft(path)
    rep = Report(d)
    close = False
    if con is None:
        con = home.connect()
        close = True
    try:
        facts = load_facts(con)
    finally:
        if close:
            con.close()
    L = d.body_line
    lines = d.body.split("\n")

    # ---------- Gate A: fact gate ----------
    for rule in ("unsourced-number", "fact-missing", "fact-incomplete"):
        rep.ok("fact", rule)
    fence = False
    for i, raw in enumerate(lines):
        if raw.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        masked = _mask(raw, cfg["number_allowlist"], cfg["placeholder_tokens"])
        pos = 0
        for sent in re.split(r"(?<=[。！？!?])", masked):
            if not re.search(r"\{(own|watched|visited)\}", sent):
                for m in NUM_RE.finditer(sent):
                    ctx = sent[max(0, m.start() - 8): m.end() + 8].strip()
                    rep.add("fact", "unsourced-number", L + i,
                            "數字「%s」沒有來源：請包進 [[fact:ID|…]]，或用 {own:…} 標成自己的觀察。…%s…"
                            % (m.group(0).strip(), ctx))
            pos += len(sent)
    for i, raw in enumerate(lines):
        for m in FACT_RE.finditer(raw):
            fid = int(m.group(1))
            f = facts.get(fid)
            if f is None:
                rep.add("fact", "fact-missing", L + i, "fact:%d 不在 facts 資料表。" % fid)
                continue
            miss = [n for n, k in (("來源網址 source_url", "source_url"), ("抓取日期 retrieved_at", "retrieved_at"))
                    if not (f[k] or "").strip()]
            if miss:
                rep.add("fact", "fact-incomplete", L + i, "fact:%d 缺 %s。" % (fid, "、".join(miss)))
            if not m.group(2) and f["number"] is None and not f["claim"]:
                rep.add("fact", "fact-incomplete", L + i, "fact:%d 沒有數字也沒有敘述。" % fid)

    # ---------- De-AI lint ----------
    for rule in ("banned-phrase", "scaffolding", "same-opening", "flat-rhythm",
                 "no-first-hand", "no-change-my-mind", "placeholder"):
        rep.ok("lint", rule)
    fence = False
    for i, raw in enumerate(lines):
        if raw.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        low = raw.lower()
        for ph in cfg["banned_phrases"]:
            if ph.lower() in low:
                rep.add("lint", "banned-phrase", L + i, "客套或 AI 慣用語「%s」：刪掉或重寫。" % ph)
        for pat in cfg["banned_patterns"]:
            m = re.search(pat["regex"], raw)
            if m:
                rep.add("lint", "banned-phrase", L + i, "句型「%s」：%s" % (pat["label"], m.group(0)))
        for tok in cfg["placeholder_tokens"]:
            if tok in raw:
                rep.add("lint", "placeholder", L + i, "還有沒填的骨架占位「%s…」。" % tok)

    # scaffolding 首先/其次/最後
    for group in cfg["scaffold_groups"]:
        hits = {}
        for i, raw in enumerate(lines):
            for sent in SENT_SPLIT.split(raw):
                s = sent.strip().lstrip("-*> ").lower()
                for w in group:
                    if s.startswith(w.lower()):
                        hits.setdefault(w, L + i)
        if len(hits) >= 2:
            first = min(hits.values())
            rep.add("lint", "scaffolding", first,
                    "「%s」排比骨架：改成自然的敘述順序。" % "、".join(sorted(hits, key=hits.get)))

    paras = [(i, strip_markers(t, facts)) for i, t in paragraphs(d.body)]
    k = int(cfg["opening_chars"])
    a = 0
    while a < len(paras) - 2:
        heads = [re.sub(r"\s+", "", p[1])[:k] for p in paras[a:a + 3]]
        is_ph = any(heads[0] and tok.startswith(heads[0]) for tok in cfg["placeholder_tokens"])
        if len(heads[0]) == k and heads[0] == heads[1] == heads[2] and not is_ph:
            rep.add("lint", "same-opening", L + paras[a][0],
                    "連續三段都用「%s」開頭：換一種寫法。" % heads[0])
            a += 3
        else:
            a += 1

    sents = []
    for _, t in paras:
        sents += [len(re.sub(r"\s+", "", s)) for s in SENT_SPLIT.split(t) if len(re.sub(r"\s+", "", s)) >= 2]
    if len(sents) >= int(cfg["min_sentences_for_rhythm"]):
        mean = sum(sents) / len(sents)
        sd = math.sqrt(sum((x - mean) ** 2 for x in sents) / len(sents))
        cv = sd / mean if mean else 0
        if cv < float(cfg["min_sentence_cv"]):
            rep.add("lint", "flat-rhythm", None,
                    "句子長度太整齊（變異係數 %.2f，低於 %.2f）：長句後面接短句。" % (cv, cfg["min_sentence_cv"]))

    markers = "|".join(cfg["first_hand_markers"])
    if not re.search(r"\{(%s)(:[^{}]*)?\}" % markers, d.body):
        rep.add("lint", "no-first-hand", None,
                "沒有一手證據標記：至少一處用 {own:…}、{watched:…} 或 {visited:…} 標出你看過、走過或算過的內容。")

    found = False
    for head, idx, sec_lines in sections(d.body):
        if head and re.search(cfg["change_mind_heading"], head, flags=re.I):
            text = strip_markers("".join(sec_lines), facts)
            for tok in cfg["placeholder_tokens"]:
                text = re.sub(re.escape(tok) + r"[^】]*】", "", text)
            if len(re.sub(r"\s+", "", text)) >= int(cfg["change_mind_min_chars"]):
                found = True
            else:
                rep.add("lint", "no-change-my-mind", L + idx, "「什麼情況下我會改口」這一節是空的。")
                found = True
    if not found:
        rep.add("lint", "no-change-my-mind", None,
                "沒有「什麼情況下我會改口」一節（標題需含「改口」或 change my mind）。")
    rep.issues.sort(key=lambda x: (x[0] != "fact", x[2] or 0))
    return rep, cfg

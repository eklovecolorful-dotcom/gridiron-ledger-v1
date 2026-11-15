"""`ledger publish`: gate A + gate B, then idempotent per-platform staging.

Adapters are STUBS: they write a ready-to-paste file under 30-published/ and
never call a social, email or payment API.
"""
import json
import re

from .core import LedgerError, PLATFORMS, PUBLISH_PLATFORMS, now
from .draft import Draft, load_facts, paragraphs, sections, strip_markers, fact_text
from .lint import check_draft

DEFAULT_LIMITS = {
    "_note": "字數上限。threads 與 linkedin 來自藍圖；其餘是起始預設值，請依各平台現行規定調整。",
    "threads": 500, "linkedin": 400, "fb": 300, "ig_caption": 300, "ig_card": 60, "email_preheader": 60,
}
NAMES = {"site": "網站", "threads": "Threads", "ig": "Instagram", "fb": "Facebook", "yt": "YouTube Shorts",
         "linkedin": "LinkedIn", "email": "電子報 Email", "medium": "Medium", "vocus": "方格子 vocus"}


def limits(home):
    lim = dict(DEFAULT_LIMITS)
    p = home / "50-prompts" / "platforms" / "limits.json"
    if p.exists():
        lim.update({k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if not k.startswith("_")})
    return lim


def tracked_url(cfg, platform, cid):
    return "%s/go/%s-%s/?src=%s&c=%s" % (cfg["base_url"].rstrip("/"), platform, cid, platform, cid)


def store_link(con, cfg, platform, cid):
    url = tracked_url(cfg, platform, cid)
    con.execute("INSERT INTO links(content_id,platform,url,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(content_id,platform) DO UPDATE SET url=excluded.url", (cid, platform, url, now()))
    return url


def _sentences(text):
    return [s.strip() for s in re.findall(r"[^。！？!?]+[。！？!?]?", text) if s.strip()]


def fit(sentences, limit):
    """Join whole sentences without exceeding `limit` characters."""
    out = ""
    for s in sentences:
        if len(out) + len(s) > limit:
            break
        out += s
    if not out and sentences:
        out = sentences[0][:max(0, limit - 1)] + "…"
    return out


class Piece:
    """Plain-text view of an approved draft, used by every adapter."""

    def __init__(self, home, d, facts):
        self.d, self.cfg, self.lim = d, home.config(), limits(home)
        self.cid = d.content_id
        self.title = str(d.meta.get("title", self.cid))
        self.summary = str(d.meta.get("summary", ""))
        self.facts = facts
        self.paras = [strip_markers(t, facts) for _, t in paragraphs(d.body)]
        self.secs = []
        for head, _, lines in sections(d.body):
            body = "\n".join(l for l in lines if not l.strip().startswith(">"))
            ps = [strip_markers(t, facts) for _, t in paragraphs(body)]
            if ps:
                self.secs.append((head, ps))
        self.sent = [s for p in self.paras for s in _sentences(p)]
        # social posts lead with the "my read" section when the draft has one
        read = [ps for head, ps in self.secs if re.search(r"判讀|my read", head, flags=re.I)]
        self.hook = [s for p in (read[0] if read else self.paras) for s in _sentences(p)]
        self.article_url = "%s/articles/%s/" % (self.cfg["base_url"].rstrip("/"), self.cid)

    def link(self, platform):
        return tracked_url(self.cfg, platform, self.cid)

    def sources(self):
        out = []
        for n, fid in enumerate(self.d.fact_ids(), 1):
            f = self.facts.get(fid)
            if f:
                out.append("%d. %s — %s（擷取 %s）" % (n, f["claim"], f["source_url"], f["retrieved_at"]))
        return out

    def full_markdown(self):
        body = strip_markers(self.d.body, self.facts)
        return body.strip()


def _head(piece, platform, note):
    return ("<!-- 待貼稿 READY TO PASTE · %s · %s v%d\n     未自動發布 NOT POSTED: v1 不呼叫任何社群、電子報或金流 API，請手動貼上。\n     %s\n     貼出後執行：ledger posted %s --platform %s --url <實際網址>\n-->\n\n"
            % (NAMES[platform], piece.cid, piece.d.version, note, piece.cid, platform))


def a_threads(p):
    link = p.link("threads")
    budget = p.lim["threads"] - len(link) - 2
    text = fit(([p.summary] if p.summary else []) + p.hook, budget)
    post = text + "\n\n" + link
    assert len(post) <= p.lim["threads"]
    return _head(p, "threads", "上限 %d 字（含連結），目前 %d 字。" % (p.lim["threads"], len(post))) + post + "\n"


def a_linkedin(p):
    text = fit(([p.summary] if p.summary else []) + p.hook, p.lim["linkedin"])
    return (_head(p, "linkedin", "正文約 %d 字，目前 %d 字。" % (p.lim["linkedin"], len(text)))
            + text + "\n\n企業內訓或委稿想看樣稿，歡迎私訊或來信。\n全文與來源：" + p.link("linkedin") + "\n")


def a_fb(p):
    text = fit(([p.summary] if p.summary else []) + p.hook, p.lim["fb"])
    return _head(p, "fb", "正文上限 %d 字，目前 %d 字。" % (p.lim["fb"], len(text))) + text + "\n\n全文：" + p.link("fb") + "\n"


def a_ig(p):
    cards = ["1｜" + p.title]
    for i, (head, ps) in enumerate(p.secs, 2):
        first = fit(_sentences(ps[0]), p.lim["ig_card"])
        cards.append("%d｜%s%s" % (i, (head + "：") if head else "", first))
    cards.append("%d｜全文與來源在個人檔案連結" % (len(cards) + 1))
    cap = fit(([p.summary] if p.summary else []) + p.hook, p.lim["ig_caption"])
    return (_head(p, "ig", "輪播圖卡大綱＋說明文字。圖卡請用自繪圖，不放比賽畫面。")
            + "## 圖卡大綱\n\n" + "\n".join(cards) + "\n\n## 說明文字\n\n" + cap
            + "\n\n連結放在個人檔案（IG 內文連結無法點擊）：\n" + p.link("ig") + "\n")


def a_yt(p):
    return (_head(p, "yt", "Shorts 腳本骨架。畫面用自繪戰術圖與原創旁白，不放比賽畫面。")
            + "## 標題\n\n" + p.title + "\n\n## 腳本（一個動作、一個問題、停格讓觀眾先猜）\n\n"
            + "- 開場問題：【你來寫：一句話問觀眾】\n- 停格：【你來寫：停在哪一張自繪圖】\n- 解答：" + fit(p.hook, 120)
            + "\n- 收尾：全文連結在說明欄。\n\n## 說明欄\n\n" + p.summary + "\n全文與來源：" + p.link("yt") + "\n")


def a_email(p):
    pre = fit(_sentences(p.summary) or p.sent, p.lim["email_preheader"])
    body = "\n\n".join(p.paras[:4])
    return (_head(p, "email", "電子報免費摘要版。v1 不寄信：請貼到你的電子報服務。")
            + "主旨 Subject：" + p.title + "\n預覽文字 Preheader：" + pre + "\n\n---\n\n" + body
            + "\n\n繼續讀全文與來源列表：\n" + p.link("email")
            + "\n\n---\n球場帳本 Gridiron Ledger｜非官方獨立評論，不提供投注建議。\n不想再收到，回信告訴我就會移除。\n")


def a_longform(platform):
    def run(p):
        note = "發表已完成的專欄並標明原始出處。"
        if platform == "medium":
            note += "Medium 要求揭露 AI 生成文字；請先讀它的現行規定再決定是否放進付費牆。"
        src = "\n".join(p.sources())
        return (_head(p, platform, note) + "# " + p.title + "\n\n" + p.full_markdown()
                + "\n\n---\n\n## 來源\n\n" + (src or "（本文沒有引用 facts）")
                + "\n\n原文刊於球場帳本：" + p.link(platform) + "\n非官方獨立評論。AI 使用範圍見本站「關於」頁。\n")
    return run


def a_site(p):
    return ("<!-- 網站版已由 ledger build 產生於 site/articles/%s/ ；把 site/ 資料夾部署出去才算上線。 -->\n\n%s\n"
            % (p.cid, p.article_url))


ADAPTERS = {"site": a_site, "threads": a_threads, "linkedin": a_linkedin, "fb": a_fb, "ig": a_ig, "yt": a_yt,
            "email": a_email, "medium": a_longform("medium"), "vocus": a_longform("vocus")}


def publish(home, con, path, platforms, out=print):
    """Returns dict platform -> 'published' | 'already' | 'failed'. Raises LedgerError if a gate refuses."""
    from . import site as site_mod
    rep, cfg_lint = check_draft(home, path, con)
    d = rep.draft
    if not rep.passed(cfg_lint):
        raise LedgerError("拒絕發布 REFUSED：check 沒過（閘門 A／去 AI 化）。先執行 ledger check %s" % path)
    if not d.approved:
        raise LedgerError("拒絕發布 REFUSED：稿件尚未核准（閘門 B）。檔頭需為 approved: true，或執行 ledger approve %s" % path)
    sha = d.meta.get("approved_sha")
    if sha and str(sha) != d.body_sha():
        raise LedgerError("拒絕發布 REFUSED：核准之後內文有改動。請重新執行 ledger approve %s" % path)
    for p in platforms:
        if p not in PUBLISH_PLATFORMS:
            raise LedgerError("不認得的平台：%s（可用：%s）" % (p, ", ".join(PUBLISH_PLATFORMS)))
    cid, ver = d.content_id, d.version
    todo, result = [], {}
    for p in platforms:
        row = con.execute("SELECT status,published_at FROM posts WHERE content_id=? AND platform=? AND version=?",
                          (cid, p, ver)).fetchone()
        if row and row["status"] in ("staged", "published"):
            result[p] = "already"
            out("  = %-9s already published（v%d，%s）— 不重複動作" % (p, ver, row["published_at"]))
        else:
            todo.append(p)
    if not todo:
        return result
    site_mod.build(home, con)
    out("  · 已重建網站 site/")
    facts = load_facts(con)
    piece = Piece(home, d, facts)
    dest = home / "30-published" / cid
    dest.mkdir(parents=True, exist_ok=True)
    fact_ids = ",".join(str(i) for i in d.fact_ids())
    cfg = home.config()
    for p in todo:
        url = piece.article_url if p == "site" else store_link(con, cfg, p, cid)
        try:
            text = ADAPTERS[p](piece)
            (dest / ("%s.md" % p)).write_text(text, encoding="utf-8")
            status, err = "staged", None
        except Exception as e:  # one platform failing must not block the others
            status, err = "failed", "%s: %s" % (type(e).__name__, e)
        con.execute(
            "INSERT INTO posts(content_id,game_id,platform,version,status,url,published_at,fact_ids,error) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(content_id,platform,version) DO UPDATE SET status=excluded.status,url=excluded.url,"
            "published_at=excluded.published_at,fact_ids=excluded.fact_ids,error=excluded.error",
            (cid, str(d.meta.get("game", "")), p, ver, status, url, now(), fact_ids, err))
        con.commit()
        if status == "failed":
            result[p] = "failed"
            out("  ! %-9s FAILED：%s — 再跑一次只會重試這個平台" % (p, err))
        else:
            result[p] = "published"
            out("  + %-9s 待貼稿已寫入 30-published/%s/%s.md" % (p, cid, p))
    if d.meta.get("status") != "published" and "failed" not in result.values():
        d.save_meta(status="published")
    return result

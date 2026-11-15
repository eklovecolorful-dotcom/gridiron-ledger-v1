"""`ledger build`: static site from approved drafts + SQLite. No framework."""
import datetime as _dt
import hashlib
import json
import shutil
import struct
import zlib
from urllib.parse import urlsplit

from . import md
from .core import PILLARS, PLATFORMS, today
from .draft import Draft, load_facts, sections, strip_markers
from .md import esc
from .subscribe import pick

ASSETS = __import__("pathlib").Path(__file__).resolve().parent / "assets"
NAV = [("", "首頁", "Home"), ("articles/", "文章", "Articles"), ("teams/", "球團資料表", "Teams"),
       ("predictions/", "預測紀錄", "Predictions"), ("watchlist/", "觀賽單", "Watchlist"), ("about/", "關於", "About")]
PILLAR_BLURB = {
    "reading": "每週一個戰術或規則，講到新手看得出來。",
    "ledger": "估值、股權、媒體權利金、球場開發、薪資上限。",
    "travel": "去現場看球的完整做法，與海外賽事攻略。",
}
OUTCOME = {"open": "待驗證", "hit": "說中", "miss": "說錯", "push": "無法判定"}


def approved_drafts(home):
    out = []
    for p in home.drafts():
        d = Draft(p)
        if d.approved and d.meta.get("content_id"):
            out.append(d)
    out.sort(key=lambda d: str(d.meta.get("date", "")), reverse=True)
    return out


def _png(size, path):
    """Write the brand icon as a PNG (pure stdlib): turf field, chalk yard lines, flag band."""
    turf, chalk, flag = (30, 91, 62), (242, 245, 241), (226, 168, 0)
    rows = []
    for y in range(size):
        row = bytearray()
        fy = y / size
        for x in range(size):
            fx = x / size
            col = turf
            if 0.16 < fx < 0.84:
                for k in (0.30, 0.44, 0.58):
                    if abs(fy - k) < 0.022:
                        col = chalk
                if abs(fy - 0.74) < 0.04:
                    col = flag
            row += bytes(col)
        rows.append(b"\x00" + bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


class Builder:
    def __init__(self, home, con, out=None, base_url=None):
        self.home, self.con = home, con
        self.cfg = home.config()
        if base_url:
            self.cfg["base_url"] = base_url
        self.out = out or (home / "site")
        self.base = self.cfg["base_url"].rstrip("/")
        self.adapter, self.sub_warning = pick(self.cfg)
        self.pages = []       # (path, in_sitemap)
        self.warnings = []
        self.uid = 0

    # ---------- shell ----------
    def page(self, path, title, desc, body, og_type="website", noindex=False, canonical=None,
             body_attrs="", sitemap=True, root=None):
        # root: fixed prefix for links, for pages served at unknown URLs (404.html)
        depth = path.count("/")
        rel = root if root is not None else "../" * depth
        url = self.base + "/" + (path[:-len("index.html")] if path.endswith("index.html") else path)
        canonical = canonical or url
        brand = "%s %s" % (self.cfg["brand_zh"], self.cfg["brand_en"])
        full_title = title if title == brand else "%s｜%s" % (title, self.cfg["brand_zh"])
        cur = path[:-len("index.html")] if path.endswith("index.html") else path
        nav = "".join('<a href="%s%s"%s>%s</a>' % (rel, href, ' aria-current="page"' if href == cur else "", zh)
                      for href, zh, en in NAV)
        html_ = """<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
{robots}<link rel="canonical" href="{canonical}">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="{brand}">
<meta property="og:locale" content="zh_TW">
<meta property="og:image" content="{base}/assets/icon-512.png">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#1E5B3E">
<link rel="manifest" href="{rel}manifest.webmanifest">
<link rel="icon" href="{rel}assets/icon-192.png" type="image/png">
<link rel="apple-touch-icon" href="{rel}assets/icon-192.png">
<link rel="stylesheet" href="{rel}assets/site.css">
</head>
<body data-sw="{rel}sw.js"{body_attrs}>
<a class="skip" href="#main">跳到內容</a>
<header class="mast"><div class="wrap">
<a class="brand" href="{rel}">{brand_zh} <small lang="en">{brand_en}</small></a>
<nav aria-label="主選單">{nav}</nav>
<button class="theme" type="button" data-theme-toggle aria-label="切換深色或淺色">深／淺</button>
</div></header>
<main id="main">
{body}
</main>
<footer class="foot"><div class="wrap">
<p><strong>非官方獨立評論。</strong>本站與 NFL、各球團沒有任何隸屬或合作關係，隊名僅作描述之用，不使用官方標誌。<span lang="en"> Unofficial, independent commentary; not affiliated with the NFL or any team.</span></p>
<p>不提供投注建議。數字皆附來源與擷取日期，發現錯誤請來信。<a href="{rel}about/#ai">AI 使用揭露</a> · <a href="{rel}about/">關於本站</a></p>
<p>© {year} {brand}</p>
</div></footer>
<script src="{rel}assets/site.js" defer></script>
</body>
</html>
""".format(title=esc(full_title), desc=esc(desc), canonical=esc(canonical), og_type=og_type,
           robots='<meta name="robots" content="noindex">\n' if noindex else "",
           brand=esc(brand), brand_zh=esc(self.cfg["brand_zh"]), brand_en=esc(self.cfg["brand_en"]),
           base=esc(self.base), rel=rel, nav=nav, body=body, body_attrs=body_attrs,
           year=today()[:4])
        dest = self.out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html_, encoding="utf-8")
        self.pages.append((path, sitemap and not noindex))

    def signup(self, heading="每週五收到一封信"):
        self.uid += 1
        return self.adapter.render(self.uid, heading)

    def pillar_tag(self, d):
        zh, en = PILLARS.get(d.meta.get("pillar"), ("未分類", ""))
        t = '<span class="tag">%s</span>' % esc(zh)
        if d.meta.get("sample") is True:
            t += '<span class="tag f">範例 Sample</span>'
        return t

    def post_list(self, drafts, rel):
        if not drafts:
            return '<p class="empty">還沒有已核准的文章。稿件核准後執行 <code>ledger build</code> 就會出現在這裡。</p>'
        items = []
        for d in drafts:
            items.append('<li><time datetime="%s">%s</time><div>%s<h3><a href="%sarticles/%s/">%s</a></h3><p>%s</p></div></li>' % (
                esc(d.meta.get("date", "")), esc(d.meta.get("date", "")), self.pillar_tag(d), rel,
                esc(d.content_id), esc(d.meta.get("title", d.content_id)), esc(d.meta.get("summary", ""))))
        return '<ul class="posts">%s</ul>' % "".join(items)

    # ---------- pages ----------
    def home_page(self, drafts):
        c = self.cfg
        pillars = "".join(
            '<div class="box pillar"><h3>%s</h3><p class="enl" lang="en">%s</p><p>%s</p></div>'
            % (esc(zh), esc(en), esc(PILLAR_BLURB[k])) for k, (zh, en) in PILLARS.items())
        body = """<div class="wrap">
<section class="hero">
<div><p class="kick">{bz} <span lang="en">{be}</span></p>
<h1>{tz}</h1>
<p class="lede">讀懂 NFL 這門生意，也帶你真的走進球場。每個數字都附來源與日期，每個預判都公開留底。</p>
<p class="note" lang="en">{te} Every number is sourced and dated; every prediction stays on the record.</p></div>
{signup}
</section>
<section aria-labelledby="h-pillars"><h2 class="yard" id="h-pillars"><span class="yd">10</span><span>三條內容支柱<small lang="en">Three pillars</small></span></h2>
<div class="grid3">{pillars}</div></section>
<section aria-labelledby="h-latest"><h2 class="yard" id="h-latest"><span class="yd">20</span><span>最新文章<small lang="en">Latest</small></span></h2>
{posts}</section>
<section aria-labelledby="h-tools"><h2 class="yard" id="h-tools"><span class="yd">30</span><span>留底的東西<small lang="en">On the record</small></span></h2>
<div class="grid3">
<div class="box"><h3><a href="teams/">球團資料表</a></h3><p>估值、股權、球場，每一格都有來源與日期。沒查證的就留白。</p></div>
<div class="box"><h3><a href="predictions/">預測紀錄</a></h3><p>每個預判都登記，賽後公開驗證，說錯的也留著。</p></div>
<div class="box"><h3><a href="watchlist/">本週觀賽單</a></h3><p>看球時拿在手上的檢查卡，可加入手機主畫面，離線也能用。</p></div>
</div></section>
</div>""".format(bz=esc(c["brand_zh"]), be=esc(c["brand_en"]), tz=esc(c["tagline_zh"]), te=esc(c["tagline_en"]),
                 signup=self.signup(), pillars=pillars, posts=self.post_list(drafts[:6], ""))
        self.page("index.html", "%s %s" % (c["brand_zh"], c["brand_en"]),
                  "%s。讀懂 NFL 這門生意，也帶你真的走進球場。" % c["tagline_zh"], body)

    def articles_index(self, drafts):
        body = '<div class="wrap narrow"><section class="article"><h1>文章</h1><p class="note" lang="en">All articles</p>%s</section></div>' % self.post_list(drafts, "../")
        self.page("articles/index.html", "文章", "球場帳本的所有文章：一檔看懂、球團資產、朝聖手冊。", body)

    def sources_html(self, refs, facts):
        if not refs:
            return ""
        items = []
        for n, fid in enumerate(refs, 1):
            f = facts.get(fid)
            if f is None:
                items.append('<li id="src-%d">fact:%d（資料表中找不到）</li>' % (n, fid))
                continue
            name = f["source_name"] or (f["source_url"] or "").split("/")[2] if f["source_url"] else (f["source_name"] or "")
            link = '<a href="%s" rel="noopener">%s</a>' % (esc(f["source_url"]), esc(name)) if f["source_url"] else esc(name)
            fix = ""
            if f["corrected_at"]:
                fix = ' <span class="tag w">更正 %s</span>' % esc(f["corrected_at"][:10])
            items.append('<li id="src-%d">%s<br><span class="note">來源：%s · 擷取日期 <time>%s</time></span>%s</li>'
                         % (n, esc(f["claim"]), link, esc(f["retrieved_at"] or "未記錄"), fix))
        return ('<section aria-labelledby="h-src"><h2 id="h-src">來源 <small lang="en">Sources</small></h2>'
                '<ol class="sources">%s</ol></section>' % "".join(items))

    def article_page(self, d, facts):
        refs = []
        html_body = md.render(d.body, facts, refs)
        cid = d.content_id
        version = ('<span> · 第 %d 版</span>' % d.version) if d.version > 1 else ""
        sample = ""
        if d.meta.get("sample") is True:
            sample = '<p class="callout"><strong>範例文章 Sample.</strong> 這是系統附的示範稿，用來展示格式與檢查流程。數字都附來源；開場與「我算了一下」一段是示範寫法，正式稿會換成作者自己看過、走過或算過的內容。</p>'
        body = """<div class="wrap narrow"><article class="article">
<header><p>{tag}</p><h1>{title}</h1>
<p class="meta"><time datetime="{date}">{date}</time>{version}{author}</p></header>
{sample}<div class="body">
{html}
</div>
{sources}
<hr>
{signup}
<p class="note" style="margin-top:18px">非官方獨立評論。本文的主張由作者撰寫，AI 的使用範圍見 <a href="../../about/#ai">AI 使用揭露</a>。</p>
</article></div>""".format(tag=self.pillar_tag(d), title=esc(d.meta.get("title", cid)), date=esc(d.meta.get("date", "")),
                           version=version, author=(" · " + esc(self.cfg["author"])) if self.cfg.get("author") else "",
                           sample=sample, html=html_body, sources=self.sources_html(refs, facts),
                           signup=self.signup("想每週收到這樣的文章？"))
        self.page("articles/%s/index.html" % cid, d.meta.get("title", cid), d.meta.get("summary", ""), body, og_type="article")

    def landing_pages(self, d, facts):
        """/go/<src>-<content_id>/ — shows the promised content first, then the signup."""
        cid = d.content_id
        lead = []
        for head, _, lines in sections(d.body):
            text = "\n".join(l for l in lines if not l.strip().startswith(">")).strip()
            if text:
                lead.append(("## %s\n\n" % head if head else "") + text)
            if len(lead) == 2:
                break
        excerpt = md.render("\n\n".join(lead), facts, None)
        ep = self.cfg.get("events_endpoint") or ""
        for src in PLATFORMS:
            attrs = ' data-src="%s" data-c="%s"' % (esc(src), esc(cid))
            if ep:
                attrs += ' data-endpoint="%s"' % esc(ep)
            body = """<div class="wrap narrow"><article class="article">
<header><p>{tag}</p><h1>{title}</h1><p class="lede" style="margin:0">{summary}</p></header>
<div class="body">{excerpt}</div>
<p><a class="b primary" href="../../articles/{cid}/">讀完整篇與來源列表</a></p>
<hr>
{signup}
</article></div>""".format(tag=self.pillar_tag(d), title=esc(d.meta.get("title", cid)), summary=esc(d.meta.get("summary", "")),
                           excerpt=excerpt, cid=esc(cid), signup=self.signup("每週五收到下一篇"))
            self.page("go/%s-%s/index.html" % (src, cid), d.meta.get("title", cid), d.meta.get("summary", ""), body,
                      og_type="article", noindex=True, canonical="%s/articles/%s/" % (self.base, cid),
                      body_attrs=attrs, sitemap=False)

    def about_page(self):
        c = self.cfg
        body = """<div class="wrap narrow"><section class="article">
<h1>關於{bz}</h1>
<p class="lede">{tz}。作者在台灣，從投資與帶團的角度寫 NFL：球隊為什麼值這麼多錢，以及怎麼真的走進球場看一場球。</p>
<div class="en" lang="en"><b>About.</b> {be} is an independent, Taiwan-based publication that reads NFL franchises as assets and gameday as a trip worth planning. Unofficial; not affiliated with the NFL or any team.</div>
<h2>三條支柱</h2>
<ul><li><strong>一檔看懂</strong> <span lang="en">Reading the Game</span>：每週一個戰術或規則。</li>
<li><strong>球團資產</strong> <span lang="en">The Franchise Ledger</span>：估值、股權、媒體權利金、球場開發、薪資上限。</li>
<li><strong>朝聖手冊</strong> <span lang="en">Gameday Travel</span>：去現場看球的做法。</li></ul>
<h2 id="ai">AI 使用揭露 <small lang="en">AI-use disclosure</small></h2>
<p>原則只有一條：主張由作者寫，AI 負責整理、反駁與排版。</p>
<ul><li><strong>AI 會做的事：</strong>把公開資料整理成表、列出反方解釋、檢查稿件有沒有缺來源的數字、標出翻譯腔與重複句式、在稿件核准後改寫成各平台的長度。</li>
<li><strong>AI 不做的事：</strong>決定立場與結論、憑記憶補數字、撰寫現場經驗與個人故事、未經作者核准直接發布。</li></ul>
<p>每篇文章發布前要過兩道人工閘門：核對數字，以及作者本人核准。</p>
<div class="en" lang="en"><b>AI disclosure.</b> The author writes the claims. AI tools are used to organise public data, argue the other side, flag unsourced numbers and awkward phrasing, and reformat approved text for each platform. AI does not decide positions, supply numbers from memory, write first-hand experience, or publish without the author's approval.</div>
<h2>數字與更正 <small lang="en">Numbers and corrections</small></h2>
<p>文中每個數字都對應一筆來源與擷取日期，列在文末。來源更正或我們寫錯時，會更新文章並標示更正日期。<a href="../predictions/">預測紀錄</a>裡說錯的預判不會刪除。</p>
<h2>不做的事 <small lang="en">What this site does not do</small></h2>
<ul><li>不提供投注建議，也不導流到任何博彩網站。</li>
<li>不使用比賽畫面與官方標誌。</li>
<li>不直接販售旅遊行程；旅遊相關內容若涉及報名，會交由持照旅行社辦理。</li></ul>
<h2>聯絡 <small lang="en">Contact</small></h2>
<p>更正、合作與企業內訓詢問：<a href="mailto:{mail}">{mail}</a></p>
{signup}
</section></div>""".format(bz=esc(c["brand_zh"]), be=esc(c["brand_en"]), tz=esc(c["tagline_zh"]),
                           mail=esc(c["contact_email"]), signup=self.signup())
        self.page("about/index.html", "關於與 AI 使用揭露", "球場帳本是誰寫的、數字怎麼核對、AI 用在哪裡、不做哪些事。", body)

    def predictions_page(self):
        rows = self.con.execute("SELECT * FROM predictions ORDER BY made_at DESC, id DESC").fetchall()
        hit = sum(1 for r in rows if r["outcome"] == "hit")
        miss = sum(1 for r in rows if r["outcome"] == "miss")
        if rows:
            trs = "".join(
                "<tr><td class='n'>%d</td><td><time>%s</time></td><td>%s</td><td>%s%s</td><td><span class='tag%s'>%s</span></td><td>%s</td></tr>" % (
                    r["id"], esc(r["made_at"][:10]), esc(r["game_id"] or "—"), esc(r["claim"]),
                    ("<br><span class='note'>%s</span>" % esc(r["note"])) if r["note"] else "",
                    {"hit": "", "miss": " w", "open": " f", "push": " f"}[r["outcome"]], OUTCOME[r["outcome"]],
                    esc((r["checked_at"] or "")[:10]) or "—") for r in rows)
            table = ('<div class="scroll"><table><thead><tr><th class="n">#</th><th>登記日期</th><th>場次</th><th>預判</th><th>結果</th><th>驗證日期</th></tr></thead>'
                     '<tbody>%s</tbody></table></div>' % trs)
        else:
            table = '<p class="empty">還沒有登記任何預判。</p>'
        body = """<div class="wrap"><section class="article">
<h1>預測紀錄</h1>
<p class="lede">每個預判在賽前登記，賽後公開驗證。說錯的也留著。</p>
<p class="note" lang="en">Public prediction ledger: logged before the fact, checked after, misses kept.</p>
<p>已驗證 <strong>{done}</strong> 筆：說中 <strong>{hit}</strong>、說錯 <strong>{miss}</strong>；待驗證 <strong>{open}</strong> 筆。</p>
{table}
<p class="note">這是對球賽與球團經營的判讀紀錄，不是投注建議。</p>
</section></div>""".format(done=hit + miss, hit=hit, miss=miss, open=sum(1 for r in rows if r["outcome"] == "open"), table=table)
        self.page("predictions/index.html", "預測紀錄", "球場帳本的公開預測紀錄：賽前登記、賽後驗證，說錯的也留著。", body)

    def teams_page(self):
        rows = self.con.execute("SELECT * FROM teams ORDER BY team").fetchall()

        def cell(v, cls=""):
            if v is None or v == "":
                return '<td class="blank %s">—</td>' % cls
            return '<td class="%s">%s</td>' % (cls, esc(v))
        trs = []
        for r in rows:
            src = r["valuation_source"]
            src_html = '<td class="blank">—</td>'
            if src:
                src_html = '<td><a href="%s" rel="noopener">%s</a></td>' % (esc(src), esc(src.split("/")[2] if "//" in src else src))
            val = None if r["valuation_usd_b"] is None else ("%g" % r["valuation_usd_b"])
            trs.append("<tr><th scope='row'>%s</th>%s%s%s%s%s</tr>" % (
                esc(r["team"]), cell(val, "n"), src_html, cell(r["valuation_date"]), cell(r["stadium"]), cell(r["pe_holders"])))
        filled = sum(1 for r in rows if r["valuation_usd_b"] is not None)
        table = ('<div class="scroll"><table><thead><tr><th>球隊</th><th class="n">估值（十億美元）</th><th>來源</th><th>資料日期</th><th>球場</th><th>私募基金股東</th></tr></thead>'
                 '<tbody>%s</tbody></table></div>' % "".join(trs)) if rows else '<p class="empty">資料表是空的。</p>'
        body = """<div class="wrap"><section class="article">
<h1>球團資料表</h1>
<p class="lede">每一格都要有來源與日期才填。空白代表還沒查證，不是零。</p>
<p class="note" lang="en">Franchise table. A cell is filled only when it has a source and a date; blank means not yet verified.</p>
<p>目前 {n} 隊中有 <strong>{filled}</strong> 隊的估值已填入並附來源。</p>
{table}
<p class="note">估值為第三方媒體的估算，引用單一數字並註明出處；本站不提供整批資料下載。</p>
</section></div>""".format(n=len(rows), filled=filled, table=table)
        self.page("teams/index.html", "球團資料表", "NFL 球團估值、股權與球場資料表，每一格都附來源與日期。", body)

    def watchlist_page(self):
        p = self.home / "40-data" / "watchlist.json"
        data = {"week_id": "none", "title": "本週觀賽單", "items": []}
        if p.exists():
            data.update(json.loads(p.read_text(encoding="utf-8")))
        items = "".join(
            '<li><label><input type="checkbox" value="%s"><span>%s</span></label></li>' % (esc(it["id"]), esc(it["text"]))
            for it in data["items"])
        sample = '<span class="tag f">範例 Sample</span>' if data.get("sample") else ""
        body = """<div class="wrap narrow"><section class="article">
<h1>本週觀賽單</h1>
<p class="lede">看球時拿在手上的檢查卡。勾選狀態只存在你這台裝置上。</p>
<p class="note" lang="en">A weekly viewing checklist. Ticks are saved on this device only; works offline once loaded.</p>
<div class="card" data-watchlist="{wid}">
<p>{sample}<span class="tag">{label}</span></p>
<h2>{title}</h2>
<p class="note">完成 <span class="progress" data-progress>0 / {n}</span></p>
<ul class="checks">{items}</ul>
<p data-storage-warn hidden class="note">這個瀏覽器不允許儲存，重新整理後勾選會消失。</p>
<button class="b" type="button" data-reset>清除勾選</button>
</div>
<h2>加入主畫面 <small lang="en">Install</small></h2>
<ul><li>iPhone（Safari）：分享 → 加入主畫面。</li><li>Android（Chrome）：選單 → 安裝應用程式。</li><li>電腦（Chrome、Edge）：網址列右側的安裝圖示。</li></ul>
<noscript><p class="callout">勾選功能需要 JavaScript；沒有 JavaScript 時這張卡仍可閱讀。</p></noscript>
</section></div>""".format(wid=esc(data.get("week_id", "none")), sample=sample, label=esc(data.get("label", "")),
                           title=esc(data.get("title", "本週觀賽單")), n=len(data["items"]), items=items)
        self.page("watchlist/index.html", "本週觀賽單", "每週一張看球檢查卡，可加入主畫面，離線可用。", body)

    def static_files(self):
        a = self.out / "assets"
        a.mkdir(parents=True, exist_ok=True)
        for name in ("site.css", "site.js"):
            shutil.copyfile(ASSETS / name, a / name)
        _png(192, a / "icon-192.png")
        _png(512, a / "icon-512.png")
        c = self.cfg
        manifest = {
            "name": "%s %s" % (c["brand_zh"], c["brand_en"]), "short_name": c["brand_zh"],
            "description": c["tagline_zh"], "lang": "zh-Hant-TW", "start_url": "watchlist/", "scope": "./",
            "display": "standalone", "background_color": "#F2F5F1", "theme_color": "#1E5B3E",
            "icons": [{"src": "assets/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "assets/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}],
        }
        (self.out / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.page("offline.html", "目前離線", "目前沒有網路。",
                  '<div class="wrap narrow"><section class="article"><h1>目前離線</h1><p>這一頁還沒存到你的裝置。<a href="watchlist/">本週觀賽單</a>離線也能用。</p></section></div>',
                  noindex=True, sitemap=False)
        # The host serves 404.html at whatever URL was missed, so relative links would
        # resolve against that URL. Use absolute paths from base_url (works under a
        # sub-path such as GitHub Pages' /<repo>/).
        root = urlsplit(self.base).path.rstrip("/") + "/"
        self.page("404.html", "找不到這一頁", "找不到這一頁。",
                  '<div class="wrap narrow"><section class="article"><h1>找不到這一頁</h1><p>連結可能已更動。<a href="%s">回首頁</a></p></section></div>' % esc(root),
                  noindex=True, sitemap=False, root=root)

    def finish(self):
        urls = []
        for path, in_map in self.pages:
            if in_map:
                loc = self.base + "/" + (path[:-len("index.html")] if path.endswith("index.html") else path)
                urls.append("  <url><loc>%s</loc><lastmod>%s</lastmod></url>" % (esc(loc), today()))
        (self.out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s\n</urlset>\n' % "\n".join(urls),
            encoding="utf-8")
        (self.out / "robots.txt").write_text("User-agent: *\nAllow: /\nDisallow: /go/\n\nSitemap: %s/sitemap.xml\n" % self.base, encoding="utf-8")
        pre = ["./", "watchlist/", "offline.html", "assets/site.css", "assets/site.js", "manifest.webmanifest",
               "assets/icon-192.png", "assets/icon-512.png"]
        h = hashlib.sha256()
        for p in sorted(self.out.rglob("*")):
            if p.is_file() and p.name != "sw.js":
                h.update(p.read_bytes())
        sw = (ASSETS / "sw.js").read_text(encoding="utf-8")
        (self.out / "sw.js").write_text(sw.replace("__BUILD__", h.hexdigest()[:10]).replace("__PRECACHE__", json.dumps(pre)), encoding="utf-8")
        (self.out / ".nojekyll").write_text("", encoding="utf-8")


def build(home, con, out=None, quiet=False, base_url=None):
    b = Builder(home, con, out, base_url)
    if b.out.exists():
        shutil.rmtree(b.out)
    b.out.mkdir(parents=True)
    drafts = approved_drafts(home)
    facts = load_facts(con)
    b.static_files()
    b.home_page(drafts)
    b.articles_index(drafts)
    for d in drafts:
        b.article_page(d, facts)
        b.landing_pages(d, facts)
    b.about_page()
    b.predictions_page()
    b.teams_page()
    b.watchlist_page()
    b.finish()
    if b.sub_warning:
        b.warnings.append(b.sub_warning)
    if "example.com" in b.base:
        b.warnings.append("base_url 仍是占位值 %s：sitemap、OG 與追蹤連結會指向它，上線前請改 ledger.config.json。" % b.base)
    if b.cfg["contact_email"].endswith("example.com"):
        b.warnings.append("contact_email 仍是占位值 %s：訂閱表單會寄到這個信箱，上線前請改。" % b.cfg["contact_email"])
    return b, drafts

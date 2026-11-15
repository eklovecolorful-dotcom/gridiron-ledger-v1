"""`ledger report`: reports/weekly.html — funnel, revenue, hours, profit per hour, decision rules."""
import datetime as _dt

from .core import STREAMS, ntd, today
from .md import esc

RULES_TEXT = [
    ("clicks_no_signup", "點擊多、註冊少", "落地頁的承諾與貼文不一致", "改落地頁第一屏，使它直接呈現貼文提到的圖或觀賽單"),
    ("signup_no_open", "註冊多、很少打開電子報", "主旨或寄送時間", "測兩種主旨；週日 21:00 提醒是否有效"),
    ("open_no_paid", "打開多、很少付費", "免費與付費的差距不夠清楚", "把一個最有用的觀察點移到付費版"),
    ("paid_no_renew", "首次付費多、續訂少", "每週交付不穩，或休賽季無內容", "訪談取消者；休賽季改發選秀與球場專題，或提供年繳方案"),
    ("platform_costly", "某平台工時高、註冊少", "這個平台不適合你", "降為轉發，或停掉"),
    ("b2b_topic", "某題材企業詢問多", "你找到企業客戶的入口", "把這個題材做成固定欄目與企業樣稿"),
]
WAIT = "樣本太小，再等 sample too small, wait"


def _d(s):
    return _dt.date.fromisoformat(s[:10])


def collect(con, cfg, date_from, date_to):
    q = lambda sql, *a: con.execute(sql, a).fetchall()
    ev = q("SELECT c, src, event, COUNT(*) n, SUM(amount) amt FROM events WHERE date BETWEEN ? AND ? GROUP BY c, src, event",
           date_from, date_to)
    by_c, by_src = {}, {}
    blank = lambda: {"click": 0, "signup": 0, "open": 0, "paid": 0, "cancel": 0, "paid_amt": 0.0, "cancel_amt": 0.0}
    for r in ev:
        src = r["src"] or "other"
        for bucket, key in ((by_c, r["c"] or "(無編號)"), (by_src, src)):
            b = bucket.setdefault(key, blank())
            b[r["event"]] += r["n"]
            if r["event"] in ("paid", "cancel"):
                b[r["event"] + "_amt"] += r["amt"] or 0
    streams = {k: 0.0 for k in STREAMS}
    streams["member"] = sum(b["paid_amt"] - b["cancel_amt"] for b in by_c.values())
    rev_c = {c: b["paid_amt"] - b["cancel_amt"] for c, b in by_c.items() if b["paid_amt"] or b["cancel_amt"]}
    for r in q("SELECT stream, content_id, SUM(amount) amt FROM revenue WHERE date BETWEEN ? AND ? GROUP BY stream, content_id",
               date_from, date_to):
        streams[r["stream"]] += r["amt"]
        if r["content_id"]:
            rev_c[r["content_id"]] = rev_c.get(r["content_id"], 0) + r["amt"]
    hours = {}
    for r in q("SELECT * FROM costs WHERE substr(logged_at,1,10) BETWEEN ? AND ?", date_from, date_to):
        hours[r["content_id"]] = {"research": r["hours_research"], "write": r["hours_write"], "edit": r["hours_edit"],
                                  "dist": r["hours_dist"],
                                  "total": r["hours_research"] + r["hours_write"] + r["hours_edit"] + r["hours_dist"]}
    days = (_d(date_to) - _d(date_from)).days + 1
    revenue = sum(streams.values())
    tools = cfg["tools_monthly_ntd"] * days / 30.0
    total_hours = sum(h["total"] for h in hours.values())
    profit = revenue - tools
    demo = q("SELECT COUNT(*) n FROM events WHERE batch LIKE '%sample%' OR batch LIKE '%demo%'")[0]["n"]
    return {"from": date_from, "to": date_to, "days": days, "by_c": by_c, "by_src": by_src, "streams": streams,
            "rev_c": rev_c, "hours": hours, "revenue": revenue, "tools": tools, "profit": profit,
            "total_hours": total_hours, "per_hour": (profit / total_hours) if total_hours else None,
            "benchmark": cfg["benchmark_hourly_ntd"], "demo": demo}


def decision_rules(con, cfg, date_to):
    """Each rule: dict(key, see, suspect, do, n, metric, status in fire|quiet|wait|nodata, detail)."""
    R = cfg["rules"]
    n_min = int(R["min_sample"])
    start = (_d(date_to) - _dt.timedelta(days=int(R["window_days"]) - 1)).isoformat()
    cnt = {r["event"]: r["n"] for r in con.execute(
        "SELECT event, COUNT(*) n FROM events WHERE date BETWEEN ? AND ? GROUP BY event", (start, date_to))}
    g = lambda k: cnt.get(k, 0)
    out = []

    def rule(key, n, metric_txt, triggered, detail="", nodata=False):
        see, suspect, do = next((a, b, c) for k, a, b, c in RULES_TEXT if k == key)
        if nodata:
            status = "nodata"
        elif n < n_min:
            status = "wait"
        else:
            status = "fire" if triggered else "quiet"
        if nodata:
            metric_txt = "—"
        out.append({"key": key, "see": see, "suspect": suspect, "do": do, "n": n, "metric": metric_txt,
                    "status": status, "detail": detail})

    rate = lambda a, b: (a / b) if b else 0.0
    pct = lambda x: "%.1f%%" % (x * 100)
    r1 = rate(g("signup"), g("click"))
    rule("clicks_no_signup", g("click"), "註冊／點擊 %s（門檻 < %s）" % (pct(r1), pct(R["click_to_signup_min"])),
         r1 < R["click_to_signup_min"])
    r2 = rate(g("open"), g("signup"))
    rule("signup_no_open", g("signup"), "開信／註冊 %s（門檻 < %s）" % (pct(r2), pct(R["signup_to_open_min"])),
         r2 < R["signup_to_open_min"], nodata=(g("open") == 0 and g("signup") < n_min) or g("open") == 0,
         detail="需要 events.csv 內有 open 事件（從電子報服務匯出）")
    r3 = rate(g("paid"), g("open"))
    rule("open_no_paid", g("open"), "付費／開信 %s（門檻 < %s）" % (pct(r3), pct(R["open_to_paid_min"])),
         r3 < R["open_to_paid_min"], nodata=g("open") == 0, detail="需要 open 事件")
    r4 = rate(g("cancel"), g("paid"))
    rule("paid_no_renew", g("paid"), "取消／付費 %s（門檻 > %s）" % (pct(r4), pct(R["cancel_to_paid_max"])),
         r4 > R["cancel_to_paid_max"])
    # platform: hours vs signups
    ph = {r["platform"]: r["h"] for r in con.execute(
        "SELECT platform, SUM(hours) h FROM platform_hours WHERE date BETWEEN ? AND ? GROUP BY platform", (start, date_to))}
    src = {}
    for r in con.execute("SELECT src, event, COUNT(*) n FROM events WHERE date BETWEEN ? AND ? GROUP BY src, event", (start, date_to)):
        src.setdefault(r["src"], {})[r["event"]] = r["n"]
    if not ph:
        rule("platform_costly", 0, "—", False, nodata=True, detail="需要先用 ledger cost platform 記錄各平台工時")
    else:
        worst, worst_n, fired = None, 0, []
        for p, h in sorted(ph.items()):
            clicks = src.get(p, {}).get("click", 0)
            per = rate(src.get(p, {}).get("signup", 0), h)
            worst_n = max(worst_n, clicks)
            if clicks >= n_min and h >= R["platform_hours_min"] and per < R["platform_signups_per_hour_min"]:
                fired.append("%s（%.1f 小時、每小時 %.2f 註冊）" % (p, h, per))
        rule("platform_costly", worst_n, "；".join(fired) or "沒有平台同時達到工時與低註冊門檻", bool(fired))
    inq = con.execute("SELECT COALESCE(pillar,'(未標)') p, COUNT(*) n FROM inquiries WHERE date BETWEEN ? AND ? GROUP BY 1 ORDER BY n DESC",
                      (start, date_to)).fetchall()
    total = sum(r["n"] for r in inq)
    if not total:
        rule("b2b_topic", 0, "—", False, nodata=True, detail="需要先用 ledger inquiry add 記錄企業詢問")
    else:
        share = inq[0]["n"] / total
        rule("b2b_topic", total, "「%s」占詢問 %s（門檻 ≥ %s）" % (inq[0]["p"], pct(share), pct(R["inquiry_pillar_share_min"])),
             share >= R["inquiry_pillar_share_min"])
    return out, start


CSS = """
:root{--bg:#F2F5F1;--surface:#FFFFFF;--ink:#13201A;--muted:#51615A;--line:#D3DCD5;--turf:#1E5B3E;--turf-soft:#DCEBE1;--flag:#E2A800;--flag-soft:#FBF0CC;--flag-ink:#7A5A00;--warn:#9B2C1F;--warn-soft:#F6DEDA;
--display:"Noto Serif TC","Noto Serif CJK TC","Songti TC","PMingLiU",serif;--body:"Noto Sans TC","Noto Sans CJK TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0E1612;--surface:#16211B;--ink:#E7EEE9;--muted:#9DB0A6;--line:#2A3A31;--turf:#5FBE8D;--turf-soft:#1B3427;--flag:#F0C23B;--flag-soft:#3A3213;--flag-ink:#F0C23B;--warn:#F08D7E;--warn-soft:#3B1E1A;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:400 16px/1.75 var(--body)}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 70px}
header{border-bottom:3px solid var(--turf);padding-bottom:18px;margin-bottom:8px}
.kick{margin:0 0 6px;color:var(--turf);font-weight:700;font-size:15px}
h1{font-family:var(--display);font-weight:900;font-size:clamp(28px,4.6vw,44px);line-height:1.25;margin:0 0 8px}
h2{font-family:var(--display);font-weight:900;font-size:clamp(21px,3vw,27px);line-height:1.35;margin:40px 0 8px;display:flex;gap:14px;align-items:baseline}
h2 .yd{color:var(--turf);font-size:.8em;border-bottom:4px solid var(--flag);line-height:1.1;font-variant-numeric:tabular-nums}
h2 small{display:block;font-family:var(--body);font-weight:500;font-size:13.5px;color:var(--muted)}
p{margin:0 0 12px;max-width:50em}.note{font-size:13.5px;color:var(--muted)}
.en{border-left:4px solid var(--flag);background:var(--flag-soft);padding:9px 14px;margin:12px 0;font-size:14px;line-height:1.6;max-width:52em}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:18px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.tile small{display:block;color:var(--muted);font-size:12.5px;line-height:1.4}
.tile strong{font-size:24px;font-variant-numeric:tabular-nums;line-height:1.35;display:block}
.tile.key{border-top:4px solid var(--turf)}
.scroll{overflow-x:auto;margin:12px 0;border:1px solid var(--line);border-radius:6px;background:var(--surface)}
table{border-collapse:collapse;width:100%;min-width:620px;font-size:14.5px;line-height:1.55}
th,td{padding:9px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{background:var(--turf-soft);font-weight:700}tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.tag{display:inline-block;font-size:12.5px;font-weight:700;padding:1px 9px;border-radius:99px;background:var(--turf-soft);color:var(--turf);white-space:nowrap}
.tag.f{background:var(--flag-soft);color:var(--flag-ink)}.tag.w{background:var(--warn-soft);color:var(--warn)}.tag.m{background:var(--line);color:var(--muted)}
tr.fire td{background:var(--flag-soft)}
.empty{padding:18px;border:1px dashed var(--line);border-radius:6px;color:var(--muted)}
.chart{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px 16px;margin:12px 0;overflow-x:auto}
.chart svg{display:block;width:100%;max-width:760px;min-width:520px;height:auto}
.chart text{fill:var(--ink);font-family:var(--body);font-size:13px}.chart text.m{fill:var(--muted)}
.mini{display:inline-block;height:10px;border-radius:0 4px 4px 0;background:var(--turf);vertical-align:middle;margin-right:8px}
.warnbar{background:var(--warn-soft);color:var(--warn);border-radius:6px;padding:10px 14px;font-weight:700;margin:14px 0}
footer{margin-top:44px;border-top:1px solid var(--line);padding-top:14px;font-size:13.5px;color:var(--muted)}
@media print{body{background:#fff}}
"""


def _chart(data):
    """Horizontal bars: profit per hour by content, with the hourly benchmark as a reference line."""
    rows = []
    for c, h in sorted(data["hours"].items()):
        if h["total"] > 0:
            rows.append((c, data["rev_c"].get(c, 0) / h["total"]))
    if not rows:
        return '<p class="empty">還沒有工時紀錄。寫完每篇後執行 <code>ledger cost add</code>。</p>'
    bench = data["benchmark"]
    top = max([bench] + [v for _, v in rows]) * 1.15
    W, left, right, bar, gap = 720, 150, 90, 22, 14
    plot = W - left - right
    H = 34 + len(rows) * (bar + gap) + 26
    x = lambda v: left + plot * max(v, 0) / top
    s = ['<svg viewBox="0 0 %d %d" role="img" aria-label="各篇內容的每工時收入，對照時薪基準 %s">' % (W, H, ntd(bench))]
    for i, (c, v) in enumerate(rows):
        y = 34 + i * (bar + gap)
        w = max(x(v) - left, 0)
        s.append('<text x="%d" y="%d" text-anchor="end">%s</text>' % (left - 10, y + 16, esc(c)))
        s.append('<path d="M%d %d h%.1f a4 4 0 0 1 4 4 v%d a4 4 0 0 1 -4 4 h-%.1f z" fill="var(--turf)"><title>%s：%s／小時</title></path>'
                 % (left, y, max(w - 4, 0), bar - 8, max(w - 4, 0), esc(c), ntd(v)))
        s.append('<text x="%.1f" y="%d">%s</text>' % (x(v) + 10, y + 16, ntd(v)))
    bx = x(bench)
    s.append('<line x1="%.1f" x2="%.1f" y1="22" y2="%d" stroke="var(--flag)" stroke-width="2" stroke-dasharray="5 4"/>' % (bx, bx, H - 24))
    s.append('<text class="m" x="%.1f" y="14" text-anchor="middle">時薪基準 %s</text>' % (bx, ntd(bench)))
    s.append('<line x1="%d" x2="%d" y1="22" y2="%d" stroke="var(--line)" stroke-width="1"/>' % (left, left, H - 24))
    s.append('<text class="m" x="%d" y="%d">NT$／小時（該篇可歸因收入 ÷ 該篇工時；未分攤工具成本）</text>' % (left, H - 6))
    s.append("</svg>")
    return '<div class="chart">%s</div>' % "".join(s)


def render(con, cfg, date_from, date_to):
    d = collect(con, cfg, date_from, date_to)
    rules, rule_start = decision_rules(con, cfg, date_to)
    bench = d["benchmark"]
    ph = d["per_hour"]
    if ph is None:
        ph_txt, verdict = "—", "還沒有工時紀錄，算不出來。"
    else:
        ph_txt = ntd(ph)
        verdict = "高於時薪基準 %s。" % ntd(bench) if ph >= bench else "低於時薪基準 %s：這段期間比去打工不划算。" % ntd(bench)
    P = ['<!doctype html><html lang="zh-Hant-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
         '<meta name="robots" content="noindex"><title>每週總表 %s – %s｜球場帳本</title><style>%s</style></head><body><div class="wrap">' % (d["from"], d["to"], CSS),
         '<header><p class="kick">球場帳本 Gridiron Ledger · 每週總表 <span lang="en">Weekly review</span></p>',
         '<h1>每工時營業利潤：%s</h1>' % ph_txt,
         '<p>%s 至 %s（%d 天）。%s</p>' % (d["from"], d["to"], d["days"], verdict),
         '<div class="en" lang="en"><b>In brief.</b> Operating profit per hour for this window is %s against a benchmark of %s per hour. Attribution is first-touch only; unknown sources are listed as “other”.</div></header>'
         % (ph_txt if ph is not None else "not available yet", ntd(bench))]
    if d["demo"]:
        P.append('<p class="warnbar">含示範資料：資料庫裡有 %d 筆來自 sample／demo 檔的虛構事件，數字不代表真實成績。<span lang="en"> Contains synthetic demo events.</span></p>' % d["demo"])
    P.append('<div class="tiles">'
             '<div class="tile key"><small>每工時營業利潤 <span lang="en">Profit / hour</span></small><strong>%s</strong></div>'
             '<div class="tile"><small>收入 <span lang="en">Revenue</span></small><strong>%s</strong></div>'
             '<div class="tile"><small>工具成本（按天數攤）<span lang="en">Tools</span></small><strong>%s</strong></div>'
             '<div class="tile"><small>營業利潤 <span lang="en">Operating profit</span></small><strong>%s</strong></div>'
             '<div class="tile"><small>工時 <span lang="en">Hours</span></small><strong>%s</strong></div></div>'
             % (ph_txt, ntd(d["revenue"]), ntd(d["tools"]), ntd(d["profit"]), ("%g" % round(d["total_hours"], 1))))

    P.append('<h2><span class="yd">10</span><span>每篇的每工時收入<small lang="en">Revenue per hour by content, vs. the hourly benchmark</small></span></h2>')
    P.append(_chart(d))

    P.append('<h2><span class="yd">20</span><span>每篇漏斗：點擊 → 註冊 → 付費<small lang="en">Funnel per content (first-touch)</small></span></h2>')
    if d["by_c"]:
        rows = []
        for c, b in sorted(d["by_c"].items(), key=lambda kv: -kv[1]["click"]):
            r1 = "%.1f%%" % (b["signup"] / b["click"] * 100) if b["click"] else "—"
            r2 = "%.1f%%" % (b["paid"] / b["signup"] * 100) if b["signup"] else "—"
            rows.append("<tr><th scope='row'>%s</th><td class='n'>%d</td><td class='n'>%d</td><td class='n'>%s</td><td class='n'>%d</td><td class='n'>%s</td><td class='n'>%d</td><td class='n'>%s</td></tr>"
                        % (esc(c), b["click"], b["signup"], r1, b["paid"], r2, b["cancel"], ntd(b["paid_amt"] - b["cancel_amt"])))
        P.append('<div class="scroll"><table><thead><tr><th>內容編號</th><th class="n">點擊</th><th class="n">註冊</th><th class="n">註冊率</th><th class="n">付費</th><th class="n">付費率</th><th class="n">取消</th><th class="n">會員實收</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(rows))
        rows = []
        for s_, b in sorted(d["by_src"].items(), key=lambda kv: -kv[1]["click"]):
            rows.append("<tr><th scope='row'>%s</th><td class='n'>%d</td><td class='n'>%d</td><td class='n'>%d</td><td class='n'>%s</td></tr>"
                        % (esc(s_), b["click"], b["signup"], b["paid"], ntd(b["paid_amt"] - b["cancel_amt"])))
        P.append('<h3>依首次來源 <span class="note" lang="en">By first-touch source</span></h3><div class="scroll"><table><thead><tr><th>來源</th><th class="n">點擊</th><th class="n">註冊</th><th class="n">付費</th><th class="n">會員實收</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(rows))
    else:
        P.append('<p class="empty">這段期間沒有事件資料。從主機的分析後台匯出 events.csv，再執行 <code>ledger import-events events.csv</code>。</p>')

    P.append('<h2><span class="yd">30</span><span>收入來源<small lang="en">Revenue by stream</small></span></h2>')
    mx = max(d["streams"].values()) or 1
    rows = "".join("<tr><th scope='row'>%s <span class='note' lang='en'>%s</span></th><td><span class='mini' style='width:%dpx'></span></td><td class='n'>%s</td><td class='n'>%s</td></tr>"
                   % (STREAMS[k][0], STREAMS[k][1], round(180 * max(v, 0) / mx), ntd(v),
                      ("%d%%" % round(v / d["revenue"] * 100)) if d["revenue"] else "—") for k, v in d["streams"].items())
    P.append('<div class="scroll"><table><thead><tr><th>來源</th><th>比例</th><th class="n">金額</th><th class="n">占比</th></tr></thead><tbody>%s</tbody></table></div>' % rows)
    P.append('<p class="note">會員月費＝events 的 paid 金額減 cancel 金額，加上手動登記的 member 收入；其他來源用 <code>ledger revenue add</code> 登記。同一筆不要兩邊都記。</p>')

    P.append('<h2><span class="yd">40</span><span>每篇工時<small lang="en">Hours per content</small></span></h2>')
    if d["hours"]:
        rows = []
        for c, h in sorted(d["hours"].items()):
            rev = d["rev_c"].get(c, 0)
            rows.append("<tr><th scope='row'>%s</th><td class='n'>%g</td><td class='n'>%g</td><td class='n'>%g</td><td class='n'>%g</td><td class='n'>%g</td><td class='n'>%s</td><td class='n'>%s</td></tr>"
                        % (esc(c), h["research"], h["write"], h["edit"], h["dist"], h["total"], ntd(rev),
                           ntd(rev / h["total"]) if h["total"] else "—"))
        P.append('<div class="scroll"><table><thead><tr><th>內容編號</th><th class="n">研究</th><th class="n">寫作</th><th class="n">編修</th><th class="n">分發</th><th class="n">合計</th><th class="n">可歸因收入</th><th class="n">每工時</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(rows))
    else:
        P.append('<p class="empty">這段期間沒有工時紀錄。</p>')

    P.append('<h2><span class="yd">50</span><span>每月決策規則<small lang="en">Monthly decision rules (blueprint 8.2) — window %s to %s, minimum sample %d</small></span></h2>' % (rule_start, date_to, cfg["rules"]["min_sample"]))
    label = {"fire": '<span class="tag f">觸發 FIRED</span>', "quiet": '<span class="tag">未觸發</span>',
             "wait": '<span class="tag m">%s</span>' % WAIT, "nodata": '<span class="tag m">無資料 no data</span>'}
    rows = []
    for r in rules:
        action = esc(r["do"]) if r["status"] == "fire" else '<span class="note">—</span>'
        extra = ("<br><span class='note'>%s</span>" % esc(r["detail"])) if r["detail"] and r["status"] == "nodata" else ""
        rows.append("<tr class='%s'><th scope='row'>%s</th><td>%s</td><td class='n'>%d</td><td>%s%s</td><td>%s</td><td>%s</td></tr>"
                    % (r["status"], esc(r["see"]), esc(r["suspect"]), r["n"], esc(r["metric"]), extra, label[r["status"]], action))
    P.append('<div class="scroll"><table><thead><tr><th>看到什麼</th><th>先懷疑哪裡</th><th class="n">樣本 n</th><th>指標</th><th>狀態</th><th>做什麼（每次只改一個變因）</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(rows))
    P.append('<p class="note">門檻是起始假設，寫在 ledger.config.json 的 rules，可依實際資料調整。樣本數低於 %d 時不下結論。</p>' % cfg["rules"]["min_sample"])

    P.append('<h2><span class="yd">60</span><span>待驗證的預判<small lang="en">Open predictions to verify</small></span></h2>')
    op = con.execute("SELECT * FROM predictions WHERE outcome='open' ORDER BY made_at").fetchall()
    if op:
        P.append("<ul>%s</ul>" % "".join("<li>#%d（%s）%s</li>" % (r["id"], esc(r["made_at"][:10]), esc(r["claim"])) for r in op))
        P.append('<p class="note">對照上週預判寫三行驗證，再用 <code>ledger predict resolve</code> 登記結果。</p>')
    else:
        P.append('<p class="empty">沒有待驗證的預判。</p>')
    P.append('<footer>歸因規則：只記首次來源，同一筆月費不在多個平台重複計算；無法判斷的列為 other。營業利潤＝收入－工具成本（每月 %s，按天數攤），不含稅、退款手續費、廣告費與你的時間成本。產生於 %s。</footer>'
             % (ntd(cfg["tools_monthly_ntd"]), today()))
    P.append("</div></body></html>")
    return "\n".join(P), d, rules

"""Command-line interface: `python3 ledger.py <command>`."""
import argparse
import csv
import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path

from . import __version__, calc as calc_mod, report as report_mod, site as site_mod
from .core import (EVENT_TYPES, PILLARS, PKG_ROOT, PLATFORMS, PUBLISH_PLATFORMS, STREAMS, Home, LedgerError,
                   fmt_num, hash_email, init_home, now, ntd, today)
from .draft import FACT_RE, Draft, fact_text, load_facts
from .lint import check_draft
from .publish import publish as do_publish, store_link

SKELETON = """---
content_id: {cid}
title: 【待填：標題】
summary: 【待填：一句話摘要，會用在首頁、社群與 OG】
pillar: {pillar}
game: {game}
date: {date}
status: draft
approved: false
version: 1
platforms: [{platforms}]
---

## 開場畫面

【待填：用一個你親眼看過的畫面或一次帶團的經驗開場，不要用定義開場。看過的用 {{watched:…}}，走過的用 {{visited:…}} 包起來。】

## 我的判讀

【待填：先錄 5 分鐘語音，把逐字稿放在 10-notes/，再把你的判讀寫成兩三段。主張由你寫，不交給 AI。】

## 證據

【待填：每個數字都用 [[fact:ID|顯示文字]] 引用（先用 ledger fact add 建檔），自己算的或親自數的用 {{own:…}} 包起來。】

## 什麼情況下我會改口

【待填：寫出一兩個會讓你收回判讀的具體情況。】

## 接下來

【待填：CTA。例如每週五電子報、本週觀賽單，或企業樣稿索取。】
"""


def sync_usage(home, con):
    """Refresh facts.used_in from [[fact:ID]] markers in 20-drafts. Returns {fact_id: [(content_id, path)]}."""
    usage = {}
    for p in home.drafts():
        d = Draft(p)
        for fid in d.fact_ids():
            usage.setdefault(fid, []).append((str(d.meta.get("content_id", p.stem)), p))
    for r in con.execute("SELECT id FROM facts").fetchall():
        con.execute("UPDATE facts SET used_in=? WHERE id=?",
                    (",".join(sorted({c for c, _ in usage.get(r["id"], [])})), r["id"]))
    con.commit()
    return usage


def resolve_draft(home, arg):
    p = Path(arg)
    if p.exists():
        return p
    for cand in (home / "20-drafts" / arg, home / "20-drafts" / (arg + ".md")):
        if cand.exists():
            return cand
    raise LedgerError("找不到稿件：%s（可給路徑、檔名或 content_id）" % arg)


# ---------------- commands ----------------
def cmd_init(a, home):
    made = init_home(home)
    print("工作室已就緒 Studio ready: %s" % home.root)
    for m in made:
        print("  + %s" % m)
    if not made:
        print("  （已存在，沒有變更）")
    print("下一步：python3 ledger.py seed-sample   # 載入範例文章與來源")


def cmd_seed(a, home):
    con = home.connect()
    S = PKG_ROOT / "studio" / "sample"
    data = json.loads((S / "seed.json").read_text(encoding="utf-8"))
    ids = {}
    for f in data["facts"]:
        row = con.execute("SELECT id FROM facts WHERE claim=?", (f["claim"],)).fetchone()
        if row:
            ids[f["key"]] = row["id"]
            continue
        cur = con.execute("INSERT INTO facts(claim,number,unit,source_url,source_name,retrieved_at) VALUES(?,?,?,?,?,?)",
                          (f["claim"], f.get("number"), f.get("unit", ""), f["source_url"], f["source_name"], f["retrieved_at"]))
        ids[f["key"]] = cur.lastrowid
    for t in data["teams"]:
        con.execute("INSERT OR IGNORE INTO teams(team) VALUES(?)", (t,))
    for t in data["team_facts"]:
        con.execute("UPDATE teams SET valuation_usd_b=?, valuation_source=?, valuation_date=? WHERE team=? AND valuation_usd_b IS NULL",
                    (t["valuation_usd_b"], t["valuation_source"], t["valuation_date"], t["team"]))
    for p in data["predictions"]:
        if not con.execute("SELECT 1 FROM predictions WHERE claim=?", (p["claim"],)).fetchone():
            con.execute("INSERT INTO predictions(game_id,claim,made_at,note) VALUES(?,?,?,?)",
                        (p["game_id"], p["claim"], p["made_at"], p["note"]))
    con.commit()
    text = (S / "SAMPLE-pe.md").read_text(encoding="utf-8")
    text = re.sub(r"\[\[fact:@(\w+)", lambda m: "[[fact:%d" % ids[m.group(1)], text)
    dest = home / "20-drafts" / "SAMPLE-pe.md"
    if dest.exists() and not a.force:
        print("  = 20-drafts/SAMPLE-pe.md 已存在，保留不動（--force 覆蓋）")
    else:
        dest.write_text(text, encoding="utf-8")
        d = Draft(dest)
        d.save_meta(approved_sha=d.body_sha())
        print("  + 20-drafts/SAMPLE-pe.md（範例文章，已標 approved）")
    if a.with_demo_events:
        _import_events(home, con, PKG_ROOT / "examples" / "events.sample.csv", force=False)
    sync_usage(home, con)
    print("  + facts %d 筆、teams %d 隊（只有附來源的格子有值）、predictions %d 筆（範例）" % (
        len(data["facts"]), len(data["teams"]), len(data["predictions"])))
    print("下一步：python3 ledger.py check SAMPLE-pe && python3 ledger.py build")


def cmd_fact(a, home):
    con = home.connect()
    if a.fact_cmd == "add":
        cur = con.execute("INSERT INTO facts(claim,number,unit,source_url,source_name,retrieved_at) VALUES(?,?,?,?,?,?)",
                          (a.claim, a.number, a.unit or "", a.source, a.source_name, a.retrieved or today()))
        con.commit()
        print("fact:%d 已建立。稿件中這樣引用：[[fact:%d|顯示文字]]" % (cur.lastrowid, cur.lastrowid))
        if not a.source:
            print("  ! 沒有來源網址：引用它的稿件過不了閘門 A。")
    elif a.fact_cmd == "list":
        sync_usage(home, con)
        rows = con.execute("SELECT * FROM facts ORDER BY id").fetchall()
        if not rows:
            print("（facts 是空的）")
        for r in rows:
            print("fact:%-3d %s %s｜%s" % (r["id"], fmt_num(r["number"]) or "—", r["unit"], r["claim"]))
            print("         來源 %s｜擷取 %s｜用在 %s%s" % (r["source_url"] or "缺", r["retrieved_at"] or "缺", r["used_in"] or "—",
                                                    ("｜更正於 %s（原值 %s）" % (r["corrected_at"][:10], fmt_num(r["previous_number"]))) if r["corrected_at"] else ""))
    elif a.fact_cmd == "check":
        cfg = home.config()
        bad = stale = 0
        for r in con.execute("SELECT * FROM facts ORDER BY id"):
            miss = [k for k in ("source_url", "retrieved_at") if not (r[k] or "").strip()]
            if miss:
                bad += 1
                print("FAIL fact:%d 缺 %s｜%s" % (r["id"], "、".join(miss), r["claim"]))
            elif (_dt.date.fromisoformat(today()) - _dt.date.fromisoformat(r["retrieved_at"][:10])).days > cfg["fact_stale_days"]:
                stale += 1
                print("WARN fact:%d 擷取日期 %s 已超過 %d 天，建議重新查證｜%s" % (r["id"], r["retrieved_at"], cfg["fact_stale_days"], r["claim"]))
        print("facts 檢查：%d 筆缺來源或日期，%d 筆偏舊。" % (bad, stale))
        return 1 if bad else 0
    elif a.fact_cmd == "usage":
        usage = sync_usage(home, con)
        ids = [a.id] if a.id else [r["id"] for r in con.execute("SELECT id FROM facts ORDER BY id")]
        for fid in ids:
            _print_usage(home, con, fid, usage)
    elif a.fact_cmd == "correct":
        r = con.execute("SELECT * FROM facts WHERE id=?", (a.id,)).fetchone()
        if not r:
            raise LedgerError("fact:%d 不存在。" % a.id)
        con.execute("UPDATE facts SET previous_number=number, number=?, corrected_at=?, unit=COALESCE(?,unit), "
                    "source_url=COALESCE(?,source_url), retrieved_at=? WHERE id=?",
                    (a.number, now(), a.unit, a.source, a.retrieved or today(), a.id))
        con.commit()
        print("fact:%d 已更正：%s → %s %s" % (a.id, fmt_num(r["number"]) or "—", fmt_num(a.number), a.unit or r["unit"]))
        usage = sync_usage(home, con)
        n = _print_usage(home, con, a.id, usage, correcting=True)
        if n:
            print("處理順序：改稿 → 檔頭 version 加 1 → ledger check → ledger approve → ledger publish。")
    return 0


def _print_usage(home, con, fid, usage, correcting=False):
    drafts = usage.get(fid, [])
    posts = [r for r in con.execute("SELECT * FROM posts ORDER BY content_id, platform, version")
             if str(fid) in r["fact_ids"].split(",")]
    print("fact:%d 用在 %d 份稿件、%d 筆已發布紀錄%s" % (fid, len(drafts), len(posts), "，以下都要重新核對：" if correcting and (drafts or posts) else ""))
    for cid, path in drafts:
        d = Draft(path)
        for i, ln in enumerate(d.body.split("\n")):
            for m in FACT_RE.finditer(ln):
                if int(m.group(1)) == fid:
                    kind = "手寫文字，需人工改" if m.group(2) else "自動帶入新數字"
                    print("  稿件 %s  %s:%d  [%s] %s" % (cid, path.name, d.body_line + i, kind, m.group(0)))
    for r in posts:
        print("  已發布 %s  %s v%d（%s）%s" % (r["content_id"], r["platform"], r["version"], r["status"],
                                           " → 需更正後重發" if correcting else ""))
    return len(drafts) + len(posts)


def cmd_new(a, home):
    slug = re.sub(r"[^A-Za-z0-9-]+", "-", a.slug).strip("-")
    if not slug:
        raise LedgerError("slug 請用英數與連字號，例如 tech 或 pe-rule。")
    week = a.week if a.week is not None else _dt.date.fromisoformat(today()).isocalendar()[1]
    cid = a.id or "W%02d-%s" % (week, slug)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", cid):
        raise LedgerError("content_id 只能用英數、連字號與底線。")
    dest = home / "20-drafts" / ("%s.md" % cid)
    if dest.exists():
        raise LedgerError("%s 已存在。" % dest)
    plats = a.platforms or "site, threads, email"
    dest.write_text(SKELETON.format(cid=cid, pillar=a.pillar, game=a.game, date=today(), platforms=plats), encoding="utf-8")
    print("已建立 %s（content_id %s，%s）" % (dest, cid, PILLARS[a.pillar][0]))
    if a.week is None and not a.id:
        print("  注意：週次用的是 ISO 週數 %d，不是 NFL 週次；要指定請加 --week N 或 --id。" % week)


def cmd_check(a, home):
    con = home.connect()
    path = resolve_draft(home, a.draft)
    rep, cfg = check_draft(home, path, con)
    sync_usage(home, con)
    print(rep.render(cfg))
    return 0 if rep.passed(cfg) else 1


def cmd_approve(a, home):
    con = home.connect()
    path = resolve_draft(home, a.draft)
    rep, cfg = check_draft(home, path, con)
    if not rep.passed(cfg):
        print(rep.render(cfg))
        raise LedgerError("不能核准：check 沒過。")
    d = rep.draft
    if not a.yes:
        if not sys.stdin.isatty():
            raise LedgerError("閘門 B 需要你本人確認：請在終端機執行，或加 --yes。")
        ans = input("你已親自讀過《%s》並核對數字，確定核准發布？輸入 yes：" % d.meta.get("title", d.content_id))
        if ans.strip().lower() not in ("y", "yes"):
            raise LedgerError("已取消，未核准。")
    d.save_meta(approved=True, approved_sha=d.body_sha(), status="approved")
    print("已核准 APPROVED：%s v%d（內文指紋 %s；之後改內文需重新核准）" % (d.content_id, d.version, d.body_sha()))


def cmd_link(a, home):
    con = home.connect()
    url = store_link(con, home.config(), a.platform, a.content_id)
    con.commit()
    print(url)
    if "example.com" in url:
        print("  ! base_url 仍是占位值，請改 ledger.config.json。", file=sys.stderr)


def cmd_build(a, home):
    con = home.connect()
    b, drafts = site_mod.build(home, con)
    sync_usage(home, con)
    print("網站已產生 Site built: %s（%d 篇已核准文章，%d 個頁面）" % (b.out, len(drafts), len(b.pages)))
    print("  訂閱模式：%s" % b.adapter.status())
    for w in b.warnings:
        print("  ! %s" % w)
    print("  本機預覽：python3 ledger.py serve   → http://localhost:8000")


def cmd_serve(a, home):
    import functools
    import http.server
    site = home / "site"
    if not site.exists():
        raise LedgerError("還沒有 site/，請先 ledger build。")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    print("http://localhost:%d  （Ctrl+C 結束）" % a.port)
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()


def cmd_publish(a, home):
    con = home.connect()
    path = resolve_draft(home, a.draft)
    d = Draft(path)
    plats = []
    for p in a.platform or []:
        plats += [x for x in p.split(",") if x]
    if not plats or plats == ["all"]:
        plats = d.meta.get("platforms") or ["site"]
        if isinstance(plats, str):
            plats = [plats]
    print("發布 %s v%d → %s" % (d.meta.get("content_id"), d.version, ", ".join(plats)))
    res = do_publish(home, con, path, plats)
    print("注意 NOTE：v1 沒有呼叫任何社群、電子報或金流 API。社群稿是待貼檔，網站要把 site/ 部署出去才上線。")
    return 1 if "failed" in res.values() else 0


def cmd_posted(a, home):
    con = home.connect()
    cur = con.execute("UPDATE posts SET status='published', url=?, published_at=? WHERE content_id=? AND platform=? "
                      "AND version=(SELECT MAX(version) FROM posts WHERE content_id=? AND platform=?)",
                      (a.url, now(), a.content_id, a.platform, a.content_id, a.platform))
    con.commit()
    if not cur.rowcount:
        raise LedgerError("posts 裡沒有 %s／%s，請先 ledger publish。" % (a.content_id, a.platform))
    print("已記錄實際網址：%s %s → %s" % (a.content_id, a.platform, a.url))


def cmd_predict(a, home):
    con = home.connect()
    if a.predict_cmd == "add":
        cur = con.execute("INSERT INTO predictions(game_id,claim,made_at,note) VALUES(?,?,?,?)",
                          (a.game, a.claim, a.made_at or now(), a.note))
        con.commit()
        print("預判 #%d 已登記（%s）。" % (cur.lastrowid, a.made_at or now()))
    elif a.predict_cmd == "resolve":
        cur = con.execute("UPDATE predictions SET outcome=?, checked_at=?, note=COALESCE(?,note) WHERE id=?",
                          (a.outcome, now(), a.note, a.id))
        con.commit()
        if not cur.rowcount:
            raise LedgerError("沒有預判 #%d。" % a.id)
        print("預判 #%d → %s" % (a.id, site_mod.OUTCOME[a.outcome]))
    elif a.predict_cmd == "list":
        rows = con.execute("SELECT * FROM predictions ORDER BY id").fetchall()
        if not rows:
            print("（還沒有預判）")
        for r in rows:
            print("#%-3d %s  %-6s %s｜%s" % (r["id"], r["made_at"][:10], site_mod.OUTCOME[r["outcome"]], r["game_id"] or "—", r["claim"]))
    elif a.predict_cmd == "export":
        rows = con.execute("SELECT * FROM predictions ORDER BY made_at DESC, id DESC").fetchall()
        md_ = ["# 預測紀錄 Prediction ledger", "", "| # | 登記日期 | 場次 | 預判 | 結果 | 驗證日期 |", "|---|---|---|---|---|---|"]
        trs = []
        for r in rows:
            cells = [str(r["id"]), r["made_at"][:10], r["game_id"] or "—", r["claim"].replace("|", "／"),
                     site_mod.OUTCOME[r["outcome"]], (r["checked_at"] or "—")[:10]]
            md_.append("| " + " | ".join(cells) + " |")
            trs.append("<tr>" + "".join("<td>%s</td>" % site_mod.esc(c) for c in cells) + "</tr>")
        out = home / "30-published"
        (out / "predictions.md").write_text("\n".join(md_) + "\n", encoding="utf-8")
        (out / "predictions.html").write_text(
            "<table>\n<thead><tr><th>#</th><th>登記日期</th><th>場次</th><th>預判</th><th>結果</th><th>驗證日期</th></tr></thead>\n<tbody>\n%s\n</tbody>\n</table>\n" % "\n".join(trs),
            encoding="utf-8")
        print("已匯出 %d 筆：30-published/predictions.md、predictions.html（網站的預測紀錄頁由 ledger build 直接從資料庫產生）" % len(rows))


def cmd_member(a, home):
    con = home.connect()
    if a.member_cmd == "import":
        salt = home.salt()
        n = skipped = 0
        with open(a.csv, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                email = (row.get("email") or "").strip()
                if "@" not in email:
                    skipped += 1
                    continue
                h = hash_email(email, salt)
                # first_source is first-touch: never overwritten once set
                con.execute(
                    "INSERT INTO members(email_hash,joined_at,first_source,plan,status) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(email_hash) DO UPDATE SET plan=excluded.plan, status=excluded.status",
                    (h, row.get("joined_at") or today(), row.get("first_source") or "other",
                     row.get("plan") or "free", row.get("status") or "active"))
                n += 1
        con.commit()
        print("已匯入 %d 位（略過 %d 列）。資料庫只存雜湊，不存 email 原文；原始名單請留在你的電子報服務並另行備份。" % (n, skipped))
    else:
        dest = Path(a.csv) if a.csv else home / "40-data" / "backups" / ("members-%s.csv" % today().replace("-", ""))
        dest.parent.mkdir(parents=True, exist_ok=True)
        rows = con.execute("SELECT * FROM members ORDER BY joined_at").fetchall()
        with open(dest, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["email_hash", "joined_at", "first_source", "plan", "status"])
            for r in rows:
                w.writerow([r["email_hash"], r["joined_at"], r["first_source"], r["plan"], r["status"]])
        print("已備份 %d 位會員到 %s（雜湊，無法還原成 email）。" % (len(rows), dest))


def cmd_cost(a, home):
    con = home.connect()
    if a.cost_cmd == "platform":
        con.execute("INSERT INTO platform_hours(date,platform,hours) VALUES(?,?,?)", (a.date or today(), a.platform, a.hours))
        con.commit()
        print("已記錄 %s 平台工時 %g 小時（只用在決策規則，不計入總工時）。" % (a.platform, a.hours))
        return
    con.execute("INSERT INTO costs(content_id,hours_research,hours_write,hours_edit,hours_dist,logged_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(content_id) DO UPDATE SET hours_research=excluded.hours_research, hours_write=excluded.hours_write, "
                "hours_edit=excluded.hours_edit, hours_dist=excluded.hours_dist, logged_at=excluded.logged_at",
                (a.content_id, a.research, a.write, a.edit, a.dist, a.date or today()))
    con.commit()
    print("%s 工時：研究 %g、寫作 %g、編修 %g、分發 %g，合計 %g 小時（同一篇再記一次會覆蓋）。"
          % (a.content_id, a.research, a.write, a.edit, a.dist, a.research + a.write + a.edit + a.dist))


def cmd_revenue(a, home):
    con = home.connect()
    con.execute("INSERT INTO revenue(date,stream,amount,content_id,note) VALUES(?,?,?,?,?)",
                (a.date or today(), a.stream, a.amount, a.content, a.note))
    con.commit()
    print("已登記收入：%s %s（%s）" % (STREAMS[a.stream][0], ntd(a.amount), a.date or today()))


def cmd_inquiry(a, home):
    con = home.connect()
    con.execute("INSERT INTO inquiries(date,pillar,content_id,source,note) VALUES(?,?,?,?,?)",
                (a.date or today(), a.pillar, a.content, a.source, a.note))
    con.commit()
    print("已登記企業詢問（題材 %s，來源 %s）。" % (a.pillar or "未標", a.source or "未標"))


def _import_events(home, con, path, force):
    path = Path(path)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if con.execute("SELECT 1 FROM imports WHERE sha=?", (sha,)).fetchone() and not force:
        print("這個檔案已匯入過（內容相同），略過。要重複匯入請加 --force。")
        return 0
    rows, bad = [], []
    reader = csv.DictReader(raw.decode("utf-8-sig").splitlines())
    need = {"date", "src", "c", "event"}
    if not reader.fieldnames or not need.issubset({f.strip() for f in reader.fieldnames}):
        raise LedgerError("events.csv 需要欄位：date,src,c,event,amount")
    for n, row in enumerate(reader, 2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        try:
            _dt.date.fromisoformat(row["date"])
            if row["event"] not in EVENT_TYPES:
                raise ValueError("event 必須是 %s" % "|".join(EVENT_TYPES))
            amt = float(row.get("amount") or 0)
        except ValueError as e:
            bad.append((n, str(e)))
            continue
        rows.append((row["date"], row["src"] or "other", row["c"], row["event"], amt, path.name))
    con.executemany("INSERT INTO events(date,src,c,event,amount,batch) VALUES(?,?,?,?,?,?)", rows)
    con.execute("INSERT OR REPLACE INTO imports(sha,filename,imported_at,rows) VALUES(?,?,?,?)", (sha, path.name, now(), len(rows)))
    con.commit()
    print("已匯入 %d 筆事件（%s）。" % (len(rows), path.name))
    for n, e in bad[:10]:
        print("  ! 第 %d 列略過：%s" % (n, e))
    return len(rows)


def cmd_import_events(a, home):
    _import_events(home, home.connect(), a.csv, a.force)


def cmd_report(a, home):
    con = home.connect()
    cfg = home.config()
    to = a.to or today()
    if a.all:
        first = con.execute("SELECT MIN(d) m FROM (SELECT MIN(date) d FROM events UNION SELECT MIN(date) FROM revenue "
                            "UNION SELECT MIN(substr(logged_at,1,10)) FROM costs)").fetchone()["m"]
        frm = first or to
    else:
        frm = a.since or (_dt.date.fromisoformat(to) - _dt.timedelta(days=a.days - 1)).isoformat()
    html_, d, rules = report_mod.render(con, cfg, frm, to)
    out = home / "reports" / "weekly.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html_, encoding="utf-8")
    print("每週總表 %s – %s → %s" % (frm, to, out))
    print("  收入 %s｜工具成本 %s｜工時 %g｜每工時營業利潤 %s（基準 %s）" % (
        ntd(d["revenue"]), ntd(d["tools"]), d["total_hours"], ntd(d["per_hour"]) if d["per_hour"] is not None else "—", ntd(d["benchmark"])))
    label = {"fire": "觸發 FIRED", "quiet": "未觸發", "wait": report_mod.WAIT, "nodata": "無資料"}
    for r in rules:
        print("  規則｜%s：%s（n=%d）%s" % (r["see"], label[r["status"]], r["n"], (" → " + r["do"]) if r["status"] == "fire" else ""))


def cmd_calc(a, home):
    only = None
    if a.scenario:
        only = calc_mod.ALIASES.get(a.scenario, a.scenario)
        if only not in calc_mod.SCENARIOS:
            raise LedgerError("情境請用：保守／基準／進取（或 conservative / base / stretch）")
    over = {}
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        if k not in calc_mod.SCENARIOS["基準"]:
            raise LedgerError("不認得的參數 %s（可用：%s）" % (k, ", ".join(calc_mod.SCENARIOS["基準"])))
        over[k] = float(v)
    print(calc_mod.render(home.config()["benchmark_hourly_ntd"], over, only))


def cmd_team(a, home):
    con = home.connect()
    if a.team_cmd == "set":
        if a.valuation is not None and not (a.source and a.date):
            raise LedgerError("填估值時必須同時給 --source 與 --date（每個數字都要有來源與日期）。")
        con.execute("INSERT OR IGNORE INTO teams(team) VALUES(?)", (a.team,))
        for col, val in (("valuation_usd_b", a.valuation), ("valuation_source", a.source), ("valuation_date", a.date),
                         ("stadium", a.stadium), ("pe_holders", a.pe)):
            if val is not None:
                con.execute("UPDATE teams SET %s=? WHERE team=?" % col, (val, a.team))
        con.commit()
        print("已更新 %s。" % a.team)
    else:
        for r in con.execute("SELECT * FROM teams ORDER BY team"):
            print("%-24s %6s  %s  %s" % (r["team"], "—" if r["valuation_usd_b"] is None else "%g" % r["valuation_usd_b"],
                                         r["valuation_date"] or "—", r["valuation_source"] or ""))


def build_parser():
    p = argparse.ArgumentParser(prog="ledger", description="球場帳本 Gridiron Ledger — 編輯工作室 studio v%s" % __version__)
    p.add_argument("--home", help="工作室資料夾（預設為本程式所在資料夾，或環境變數 LEDGER_HOME）")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")
    sub.required = True

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "建立資料夾與 ledger.sqlite")
    s = add("seed-sample", cmd_seed, "載入範例文章、來源與球團名單")
    s.add_argument("--force", action="store_true")
    s.add_argument("--with-demo-events", action="store_true", help="同時匯入虛構的示範事件（報表會標示）")

    s = add("fact", cmd_fact, "來源與數字：add / list / check / usage / correct")
    fs = s.add_subparsers(dest="fact_cmd", metavar="<action>")
    fs.required = True
    x = fs.add_parser("add")
    x.add_argument("claim")
    x.add_argument("--number", type=float)
    x.add_argument("--unit")
    x.add_argument("--source", help="來源網址")
    x.add_argument("--source-name")
    x.add_argument("--retrieved", help="擷取日期 YYYY-MM-DD（預設今天）")
    fs.add_parser("list")
    fs.add_parser("check")
    x = fs.add_parser("usage")
    x.add_argument("id", type=int, nargs="?")
    x = fs.add_parser("correct")
    x.add_argument("id", type=int)
    x.add_argument("--number", type=float, required=True)
    x.add_argument("--unit")
    x.add_argument("--source")
    x.add_argument("--retrieved")

    s = add("new", cmd_new, "建立一篇新稿的骨架")
    s.add_argument("slug")
    s.add_argument("--pillar", choices=list(PILLARS), required=True)
    s.add_argument("--game", required=True, help="場次編號，例如 2026-W12-MIN-SF")
    s.add_argument("--week", type=int, help="NFL 週次（預設用 ISO 週數）")
    s.add_argument("--id", help="直接指定 content_id")
    s.add_argument("--platforms", help="逗號分隔，預設 site, threads, email")

    s = add("check", cmd_check, "閘門 A 數字核對 + 去 AI 化檢查")
    s.add_argument("draft")
    s = add("approve", cmd_approve, "閘門 B：你本人核准發布")
    s.add_argument("draft")
    s.add_argument("--yes", action="store_true", help="略過互動確認（代表你已親自讀過）")
    s = add("link", cmd_link, "產生並記錄追蹤連結")
    s.add_argument("content_id")
    s.add_argument("--platform", choices=PLATFORMS, required=True)
    add("build", cmd_build, "產生靜態網站 site/")
    s = add("serve", cmd_serve, "本機預覽 site/")
    s.add_argument("--port", type=int, default=8000)
    s = add("publish", cmd_publish, "發布（寫出待貼稿；不呼叫任何外部 API）")
    s.add_argument("draft")
    s.add_argument("--platform", action="append", help="可重複或用逗號分隔；省略則用檔頭的 platforms。可用：%s" % ", ".join(PUBLISH_PLATFORMS))
    s = add("posted", cmd_posted, "手動貼出後，把實際網址填回 posts")
    s.add_argument("content_id")
    s.add_argument("--platform", choices=PUBLISH_PLATFORMS, required=True)
    s.add_argument("--url", required=True)

    s = add("predict", cmd_predict, "公開預測紀錄：add / resolve / list / export")
    ps = s.add_subparsers(dest="predict_cmd", metavar="<action>")
    ps.required = True
    x = ps.add_parser("add")
    x.add_argument("claim")
    x.add_argument("--game")
    x.add_argument("--made-at")
    x.add_argument("--note")
    x = ps.add_parser("resolve")
    x.add_argument("id", type=int)
    x.add_argument("--outcome", choices=["hit", "miss", "push"], required=True)
    x.add_argument("--note")
    ps.add_parser("list")
    ps.add_parser("export")

    s = add("member", cmd_member, "會員名單：import / export（只存雜湊）")
    ms = s.add_subparsers(dest="member_cmd", metavar="<action>")
    ms.required = True
    x = ms.add_parser("import")
    x.add_argument("--csv", required=True, help="欄位：email,joined_at,first_source,plan,status")
    x = ms.add_parser("export")
    x.add_argument("--csv", help="輸出路徑（預設 40-data/backups/members-YYYYMMDD.csv）")

    s = add("cost", cmd_cost, "工時：add <content_id> / platform <platform>")
    cs = s.add_subparsers(dest="cost_cmd", metavar="<action>")
    cs.required = True
    x = cs.add_parser("add")
    x.add_argument("content_id")
    for n in ("research", "write", "edit", "dist"):
        x.add_argument("--" + n, type=float, default=0.0)
    x.add_argument("--date")
    x = cs.add_parser("platform")
    x.add_argument("platform", choices=PLATFORMS)
    x.add_argument("--hours", type=float, required=True)
    x.add_argument("--date")

    s = add("revenue", cmd_revenue, "收入：add --stream member|guide|b2b|travel|sponsor --amount N")
    rs = s.add_subparsers(dest="revenue_cmd", metavar="<action>")
    rs.required = True
    x = rs.add_parser("add")
    x.add_argument("--stream", choices=list(STREAMS), required=True)
    x.add_argument("--amount", type=float, required=True)
    x.add_argument("--date")
    x.add_argument("--content", help="可歸因的 content_id")
    x.add_argument("--note")

    s = add("inquiry", cmd_inquiry, "企業詢問：add --pillar … --source …")
    qs = s.add_subparsers(dest="inquiry_cmd", metavar="<action>")
    qs.required = True
    x = qs.add_parser("add")
    x.add_argument("--pillar", choices=list(PILLARS))
    x.add_argument("--content")
    x.add_argument("--source")
    x.add_argument("--note")
    x.add_argument("--date")

    s = add("import-events", cmd_import_events, "匯入分析事件 CSV（date,src,c,event,amount）")
    s.add_argument("csv")
    s.add_argument("--force", action="store_true")
    s = add("report", cmd_report, "產生 reports/weekly.html")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--since")
    s.add_argument("--to")
    s.add_argument("--all", action="store_true", help="涵蓋所有資料")
    s = add("calc", cmd_calc, "變現試算（保守／基準／進取）")
    s.add_argument("scenario", nargs="?")
    s.add_argument("--set", action="append", metavar="KEY=VALUE", help="覆寫參數，例如 --set mem=90")
    s = add("team", cmd_team, "球團資料表：set / list")
    ts = s.add_subparsers(dest="team_cmd", metavar="<action>")
    ts.required = True
    x = ts.add_parser("set")
    x.add_argument("team")
    x.add_argument("--valuation", type=float, help="估值（十億美元）")
    x.add_argument("--source")
    x.add_argument("--date")
    x.add_argument("--stadium")
    x.add_argument("--pe")
    ts.add_parser("list")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    home = Home(args.home)
    try:
        return args.fn(args, home) or 0
    except LedgerError as e:
        print("錯誤 ERROR：%s" % e, file=sys.stderr)
        return 1

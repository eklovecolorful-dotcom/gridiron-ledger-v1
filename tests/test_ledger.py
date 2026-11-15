"""Unit tests — run: python3 -m unittest discover -s tests -v"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studio import calc, publish as pub, report  # noqa: E402
from studio.cli import main  # noqa: E402
from studio.core import Home, LedgerError  # noqa: E402
from studio.draft import Draft  # noqa: E402
from studio.lint import check_draft  # noqa: E402

GOOD_BODY = """
## 開場

{watched:我重看了這一檔三次。}防守線站得很開。

## 我的判讀

這是故意的。教練團要的不是擒殺，是逼四分衛往右邊丟。

## 證據

[[fact:%d|這一節只派了 3 人衝傳]]。短短一句，夠了。後面的掩護區因此多了人手，傳球路線全被堵住，四分衛只好把球丟出界外。

## 什麼情況下我會改口

如果下一場同樣的站位換來的是全力衝傳，那就代表我看錯了，這只是巧合。
"""


def run(home, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--home", str(home)] + list(argv))
    return code, out.getvalue() + err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gl-test-"))
        os.environ["LEDGER_TODAY"] = "2026-11-15"
        self.assertEqual(run(self.tmp, "init")[0], 0)
        self.home = Home(self.tmp)
        self._adapters = dict(pub.ADAPTERS)

    def tearDown(self):
        pub.ADAPTERS.clear()
        pub.ADAPTERS.update(self._adapters)
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("LEDGER_TODAY", None)

    def con(self):
        return self.home.connect()

    def add_fact(self, source="https://example.com/src", number=3):
        args = ["fact", "add", "第三節只派 3 人衝傳", "--number", str(number), "--unit", "人", "--retrieved", "2026-11-15"]
        if source:
            args += ["--source", source]
        code, out = run(self.tmp, *args)
        self.assertEqual(code, 0)
        return self.con().execute("SELECT MAX(id) m FROM facts").fetchone()["m"]

    def write_draft(self, cid="W12-test", body=None, approved=False, fid=None):
        fid = fid or self.add_fact()
        p = self.tmp / "20-drafts" / (cid + ".md")
        head = "---\ncontent_id: %s\ntitle: 測試稿\nsummary: 一句摘要。\npillar: reading\ngame: G1\ndate: 2026-11-15\nstatus: draft\napproved: %s\nversion: 1\nplatforms: [site, threads]\n---\n" % (
            cid, "true" if approved else "false")
        p.write_text(head + (body if body is not None else GOOD_BODY % fid), encoding="utf-8")
        return p


class TestInit(Base):
    def test_tables_and_folders(self):
        names = {r[0] for r in self.con().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("teams", "facts", "posts", "predictions", "members", "costs"):
            self.assertIn(t, names)
        for d in ("00-inbox", "10-notes", "20-drafts", "30-published", "40-data", "50-prompts", "60-assets"):
            self.assertTrue((self.tmp / d).is_dir())
        self.assertTrue((self.tmp / "50-prompts" / "lint.json").exists())

    def test_posts_unique_constraint(self):
        import sqlite3
        con = self.con()
        con.execute("INSERT INTO posts(content_id,platform,version,status) VALUES('a','threads',1,'staged')")
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute("INSERT INTO posts(content_id,platform,version,status) VALUES('a','threads',1,'staged')")


class TestFactGate(Base):
    def test_good_draft_passes(self):
        rep, cfg = check_draft(self.home, self.write_draft())
        self.assertTrue(rep.passed(cfg), rep.render(cfg))

    def test_unsourced_number_fails_with_line(self):
        fid = self.add_fact()
        p = self.write_draft(body=(GOOD_BODY % fid) + "\n這一季他們贏了 11 場。\n", fid=fid)
        rep, cfg = check_draft(self.home, p)
        self.assertTrue(rep.fact_fail)
        hits = [(line, msg) for g, r, line, msg in rep.issues if r == "unsourced-number"]
        self.assertEqual(len(hits), 1)
        self.assertIn("11", hits[0][1])
        self.assertEqual(p.read_text(encoding="utf-8").split("\n")[hits[0][0] - 1], "這一季他們贏了 11 場。")
        self.assertEqual(run(self.tmp, "check", str(p))[0], 1)

    def test_own_marker_allows_number(self):
        fid = self.add_fact()
        p = self.write_draft(body=(GOOD_BODY % fid) + "\n{own:我自己數了 11 次。}\n", fid=fid)
        rep, cfg = check_draft(self.home, p)
        self.assertFalse(rep.fact_fail, rep.render(cfg))

    def test_fact_without_source_fails(self):
        fid = self.add_fact(source=None)
        rep, _ = check_draft(self.home, self.write_draft(fid=fid))
        self.assertIn("fact-incomplete", [r for _, r, _, _ in rep.issues])

    def test_unknown_fact_fails(self):
        rep, _ = check_draft(self.home, self.write_draft(fid=999))
        self.assertIn("fact-missing", [r for _, r, _, _ in rep.issues])

    def test_team_name_with_digits_is_allowed(self):
        fid = self.add_fact()
        p = self.write_draft(body=(GOOD_BODY % fid) + "\n對手是 49ers。\n", fid=fid)
        self.assertFalse(check_draft(self.home, p)[0].fact_fail)


class TestDeAiLint(Base):
    def rules(self, body_extra="", body=None):
        fid = self.add_fact()
        p = self.write_draft(body=body if body is not None else (GOOD_BODY % fid) + body_extra, fid=fid)
        rep, cfg = check_draft(self.home, p)
        return rep, cfg

    def test_banned_phrases_zh_and_en(self):
        rep, cfg = self.rules("\n值得注意的是，這不僅是戰術，更是態度。\n\nLet us delve into it.\n")
        msgs = " ".join(m for g, r, l, m in rep.issues if r == "banned-phrase")
        for needle in ("值得注意的是", "不僅……更……", "delve"):
            self.assertIn(needle, msgs)
        self.assertFalse(rep.passed(cfg))

    def test_scaffolding(self):
        rep, _ = self.rules("\n首先，防守站位很寬。\n\n其次，衝傳人數很少。\n\n最後，結果很好。\n")
        self.assertIn("scaffolding", rep.lint_failed_rules)

    def test_same_opening_three_paragraphs(self):
        rep, _ = self.rules("\n這個站位很寬，寬到不尋常。\n\n這個選擇有風險。\n\n這個結果說明一切，沒什麼好補充的了。\n")
        self.assertIn("same-opening", rep.lint_failed_rules)

    def test_flat_rhythm(self):
        body = "\n## 開場\n\n{own:我看了這場比賽。}\n\n" + "\n\n".join("他們這一檔選擇跑球進攻。" for _ in range(8)) + \
               "\n\n## 什麼情況下我會改口\n\n如果下一場他們改成傳球，我就承認看錯了。\n"
        rep, _ = self.rules(body=body)
        self.assertIn("flat-rhythm", rep.lint_failed_rules)

    def test_missing_first_hand_and_change_my_mind(self):
        rep, _ = self.rules(body="\n## 開場\n\n防守站得很開。這是故意的，而且不是第一次了。\n")
        self.assertIn("no-first-hand", rep.lint_failed_rules)
        self.assertIn("no-change-my-mind", rep.lint_failed_rules)

    def test_new_skeleton_fails_until_filled(self):
        self.assertEqual(run(self.tmp, "new", "tech", "--pillar", "reading", "--game", "G1", "--week", "12")[0], 0)
        self.assertEqual(run(self.tmp, "check", "W12-tech")[0], 1)

    def test_sample_article_passes(self):
        self.assertEqual(run(self.tmp, "seed-sample")[0], 0)
        rep, cfg = check_draft(self.home, self.tmp / "20-drafts" / "SAMPLE-pe.md")
        self.assertEqual(rep.issues, [], rep.render(cfg))
        self.assertEqual(run(self.tmp, "check", "SAMPLE-pe")[0], 0)

    def test_lint_is_configurable(self):
        import json
        p = self.tmp / "50-prompts" / "lint.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        cfg["banned_phrases"].append("夠了")
        p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        rep, _ = self.rules()
        self.assertIn("banned-phrase", rep.lint_failed_rules)


class TestPublish(Base):
    def test_refuses_without_approval(self):
        p = self.write_draft(approved=False)
        code, out = run(self.tmp, "publish", str(p), "--platform", "threads")
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", out)
        self.assertIn("閘門 B", out)
        self.assertEqual(self.con().execute("SELECT COUNT(*) FROM posts").fetchone()[0], 0)

    def test_refuses_when_check_fails(self):
        fid = self.add_fact()
        p = self.write_draft(body=(GOOD_BODY % fid) + "\n他們贏了 11 場。\n", approved=True, fid=fid)
        code, out = run(self.tmp, "publish", str(p), "--platform", "threads")
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", out)
        self.assertEqual(self.con().execute("SELECT COUNT(*) FROM posts").fetchone()[0], 0)
        self.assertFalse((self.tmp / "30-published" / "W12-test").exists())

    def test_refuses_when_body_changed_after_approval(self):
        p = self.write_draft()
        self.assertEqual(run(self.tmp, "approve", str(p), "--yes")[0], 0)
        p.write_text(p.read_text(encoding="utf-8") + "\n補一句話，沒有數字。\n", encoding="utf-8")
        code, out = run(self.tmp, "publish", str(p), "--platform", "threads")
        self.assertEqual(code, 1)
        self.assertIn("核准之後內文有改動", out)

    def test_idempotent(self):
        p = self.write_draft(approved=True)
        code, out = run(self.tmp, "publish", str(p), "--platform", "threads,site")
        self.assertEqual(code, 0, out)
        f = self.tmp / "30-published" / "W12-test" / "threads.md"
        self.assertTrue(f.exists())
        first = self.con().execute("SELECT * FROM posts ORDER BY platform").fetchall()
        self.assertEqual(len(first), 2)
        f.write_text("sentinel", encoding="utf-8")
        code, out = run(self.tmp, "publish", str(p), "--platform", "threads,site")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("already published"), 2)
        self.assertEqual(f.read_text(encoding="utf-8"), "sentinel")  # nothing re-written
        again = self.con().execute("SELECT * FROM posts ORDER BY platform").fetchall()
        self.assertEqual([tuple(r) for r in first], [tuple(r) for r in again])

    def test_new_version_publishes_again(self):
        p = self.write_draft(approved=True)
        run(self.tmp, "publish", str(p), "--platform", "threads")
        Draft(p).save_meta(version=2)
        code, out = run(self.tmp, "publish", str(p), "--platform", "threads")
        self.assertEqual(code, 0)
        self.assertEqual(self.con().execute("SELECT COUNT(*) FROM posts WHERE platform='threads'").fetchone()[0], 2)

    def test_failed_platform_retries_only_that_platform(self):
        p = self.write_draft(approved=True)
        calls = []
        real = dict(pub.ADAPTERS)

        def boom(piece):
            raise RuntimeError("simulated outage")
        pub.ADAPTERS["threads"] = boom
        pub.ADAPTERS["linkedin"] = lambda piece: calls.append("linkedin") or real["linkedin"](piece)
        code, out = run(self.tmp, "publish", str(p), "--platform", "threads,linkedin")
        self.assertEqual(code, 1)
        st = {r["platform"]: r["status"] for r in self.con().execute("SELECT * FROM posts")}
        self.assertEqual(st, {"threads": "failed", "linkedin": "staged"})
        pub.ADAPTERS["threads"] = lambda piece: calls.append("threads") or real["threads"](piece)
        code, out = run(self.tmp, "publish", str(p), "--platform", "threads,linkedin")
        self.assertEqual(code, 0, out)
        self.assertEqual(calls, ["linkedin", "threads"])  # linkedin not re-run
        st = {r["platform"]: r["status"] for r in self.con().execute("SELECT * FROM posts")}
        self.assertEqual(st, {"threads": "staged", "linkedin": "staged"})

    def test_threads_limit_and_tracked_link(self):
        run(self.tmp, "seed-sample")
        code, out = run(self.tmp, "publish", "SAMPLE-pe", "--platform", "threads")
        self.assertEqual(code, 0, out)
        text = (self.tmp / "30-published" / "SAMPLE-pe" / "threads.md").read_text(encoding="utf-8")
        post = text.split("-->", 1)[1].strip()
        self.assertLessEqual(len(post), 500)
        self.assertIn("?src=threads&c=SAMPLE-pe", post)
        self.assertNotIn("[[fact", post)
        self.assertNotIn("{own", post)

    def test_link_command(self):
        code, out = run(self.tmp, "link", "W12-tech", "--platform", "threads")
        self.assertIn("/go/threads-W12-tech/?src=threads&c=W12-tech", out)
        self.assertEqual(self.con().execute("SELECT COUNT(*) FROM links").fetchone()[0], 1)


class TestFactCorrection(Base):
    def test_correct_lists_affected_drafts_and_posts(self):
        fid = self.add_fact()
        a = self.write_draft("W12-a", approved=True, fid=fid)
        self.write_draft("W12-b", fid=fid)
        other = self.add_fact()
        self.write_draft("W12-c", fid=other)
        run(self.tmp, "publish", str(a), "--platform", "threads")
        code, out = run(self.tmp, "fact", "correct", str(fid), "--number", "4")
        self.assertEqual(code, 0)
        self.assertIn("W12-a", out)
        self.assertIn("W12-b", out)
        self.assertNotIn("W12-c", out)
        self.assertIn("threads v1", out)
        row = self.con().execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
        self.assertEqual((row["number"], row["previous_number"]), (4.0, 3.0))
        self.assertEqual(row["used_in"], "W12-a,W12-b")

    def test_bare_marker_picks_up_corrected_number(self):
        from studio.draft import load_facts, strip_markers
        fid = self.add_fact()
        run(self.tmp, "fact", "correct", str(fid), "--number", "4")
        self.assertEqual(strip_markers("派了 [[fact:%d]]" % fid, load_facts(self.con())), "派了 4人")


class TestSite(Base):
    def test_build_only_approved_and_required_files(self):
        run(self.tmp, "seed-sample")
        self.write_draft("W12-draft", approved=False)
        code, out = run(self.tmp, "build")
        self.assertEqual(code, 0, out)
        site = self.tmp / "site"
        for f in ("index.html", "articles/SAMPLE-pe/index.html", "about/index.html", "predictions/index.html",
                  "teams/index.html", "watchlist/index.html", "go/threads-SAMPLE-pe/index.html",
                  "manifest.webmanifest", "sw.js", "sitemap.xml", "robots.txt", "assets/icon-192.png"):
            self.assertTrue((site / f).exists(), f)
        self.assertFalse((site / "articles" / "W12-draft").exists())
        art = (site / "articles/SAMPLE-pe/index.html").read_text(encoding="utf-8")
        self.assertIn("非官方獨立評論", art)
        self.assertIn("frontofficesports.com", art)
        self.assertIn("2026-11-15", art)
        self.assertIn('lang="zh-Hant-TW"', art)
        self.assertIn('property="og:title"', art)
        self.assertNotIn("[[fact", art)
        self.assertNotIn("/go/", (site / "sitemap.xml").read_text(encoding="utf-8"))

    def test_gateway_placeholders_never_render_checkout(self):
        import json
        cfg = self.home.config()
        cfg["subscribe"]["mode"] = "ecpay"
        self.home.config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        code, out = run(self.tmp, "build")
        self.assertIn("NOT CONNECTED", out)
        home_html = (self.tmp / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn("data-signup", home_html)          # falls back to the waitlist
        self.assertNotIn("ecpay", home_html.lower())
        self.assertNotIn("信用卡", home_html)

    def test_teams_table_has_no_invented_numbers(self):
        run(self.tmp, "seed-sample")
        rows = self.con().execute("SELECT team, valuation_usd_b, valuation_source FROM teams WHERE valuation_usd_b IS NOT NULL").fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [("Dallas Cowboys", 17.0)])
        self.assertTrue(rows[0][2].startswith("https://"))
        self.assertEqual(self.con().execute("SELECT COUNT(*) FROM teams").fetchone()[0], 32)

    def test_404_links_are_absolute_under_base_path(self):
        import json
        for base, root in (("https://user.github.io/repo/", "/repo/"), ("https://example.org", "/")):
            cfg = self.home.config()
            cfg["base_url"] = base
            self.home.config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(run(self.tmp, "build")[0], 0)
            page = (self.tmp / "site" / "404.html").read_text(encoding="utf-8")
            self.assertIn('href="%sassets/site.css"' % root, page)
            self.assertIn('<a class="brand" href="%s">' % root, page)
            self.assertIn('<script src="%sassets/site.js"' % root, page)
            self.assertNotIn('href="assets/', page)


class TestReportRules(Base):
    def events(self, rows):
        p = self.tmp / "events.csv"
        lines = ["date,src,c,event,amount"]
        for date, src, c, event, n, amount in rows:
            lines += ["%s,%s,%s,%s,%s" % (date, src, c, event, amount)] * n
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        code, out = run(self.tmp, "import-events", str(p), "--force")
        self.assertEqual(code, 0, out)

    def status(self):
        rules, _ = report.decision_rules(self.con(), self.home.config(), "2026-11-15")
        return {r["key"]: r["status"] for r in rules}

    def test_small_sample_waits_even_if_threshold_met(self):
        self.events([("2026-11-10", "threads", "W12-a", "click", 29, 0)])   # 29 clicks, 0 signups
        self.assertEqual(self.status()["clicks_no_signup"], "wait")
        code, out = run(self.tmp, "report")
        self.assertIn("sample too small, wait", out)
        self.assertIn("sample too small, wait", (self.tmp / "reports" / "weekly.html").read_text(encoding="utf-8"))

    def test_fires_at_sample_30_when_threshold_met(self):
        self.events([("2026-11-10", "threads", "W12-a", "click", 30, 0)])
        self.assertEqual(self.status()["clicks_no_signup"], "fire")

    def test_quiet_when_sample_ok_but_threshold_not_met(self):
        self.events([("2026-11-10", "threads", "W12-a", "click", 40, 0), ("2026-11-11", "threads", "W12-a", "signup", 5, 0)])
        self.assertEqual(self.status()["clicks_no_signup"], "quiet")

    def test_churn_rule_and_window(self):
        self.events([("2026-11-10", "email", "W12-a", "paid", 30, 199), ("2026-11-12", "email", "W12-a", "cancel", 12, 0),
                     ("2026-09-01", "email", "W01-x", "click", 500, 0)])   # outside the 28-day window
        st = self.status()
        self.assertEqual(st["paid_no_renew"], "fire")
        self.assertEqual(st["clicks_no_signup"], "wait")

    def test_profit_per_hour_and_first_touch_revenue(self):
        self.events([("2026-11-12", "linkedin", "W12-a", "paid", 2, 199)])
        run(self.tmp, "revenue", "add", "--stream", "b2b", "--amount", "30000", "--date", "2026-11-13")
        run(self.tmp, "cost", "add", "W12-a", "--research", "2", "--write", "3", "--edit", "1", "--dist", "1")
        d = report.collect(self.con(), self.home.config(), "2026-11-09", "2026-11-15")
        self.assertEqual(d["streams"]["member"], 398)
        self.assertEqual(d["by_src"]["linkedin"]["paid"], 2)
        self.assertEqual(d["revenue"], 30398)
        self.assertEqual(d["total_hours"], 7)
        self.assertAlmostEqual(d["per_hour"], (30398 - 1500 * 7 / 30) / 7)

    def test_import_is_not_duplicated(self):
        p = self.tmp / "e.csv"
        p.write_text("date,src,c,event,amount\n2026-11-10,threads,W12-a,click,0\n", encoding="utf-8")
        run(self.tmp, "import-events", str(p))
        run(self.tmp, "import-events", str(p))
        self.assertEqual(self.con().execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)


class TestCalc(unittest.TestCase):
    def test_base_scenario(self):
        r = calc.compute(calc.SCENARIOS["基準"])
        self.assertEqual(round(r["revenue"]), 456820)
        self.assertEqual(r["hours"], 710)
        self.assertEqual(round(r["per_hour"]), 618)
        self.assertEqual(round(r["profit"]), 438820)

    def test_render_shows_three_scenarios(self):
        text = calc.render()
        for s in ("保守", "基準", "進取", "NT$456,820", "NT$618"):
            self.assertIn(s, text)


class TestMembersAndPredictions(Base):
    def test_member_import_stores_hash_only(self):
        p = self.tmp / "m.csv"
        p.write_text("email,joined_at,first_source,plan,status\nA@Example.com,2026-11-10,threads,free,active\n", encoding="utf-8")
        self.assertEqual(run(self.tmp, "member", "import", "--csv", str(p))[0], 0)
        p.write_text("email,joined_at,first_source,plan,status\na@example.com,2026-11-12,linkedin,member,active\n", encoding="utf-8")
        run(self.tmp, "member", "import", "--csv", str(p))
        rows = self.con().execute("SELECT * FROM members").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["first_source"], rows[0]["plan"]), ("threads", "member"))  # first-touch kept
        self.assertNotIn("example.com", self.home.db_path.read_bytes().decode("latin-1").lower())
        code, out = run(self.tmp, "member", "export")
        backup = self.tmp / "40-data" / "backups" / "members-20261115.csv"
        self.assertTrue(backup.exists())
        self.assertNotIn("@", backup.read_text(encoding="utf-8"))

    def test_prediction_ledger(self):
        run(self.tmp, "predict", "add", "測試預判", "--game", "G1")
        run(self.tmp, "predict", "resolve", "1", "--outcome", "miss")
        code, out = run(self.tmp, "predict", "list")
        self.assertIn("說錯", out)
        run(self.tmp, "predict", "export")
        self.assertIn("測試預判", (self.tmp / "30-published" / "predictions.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

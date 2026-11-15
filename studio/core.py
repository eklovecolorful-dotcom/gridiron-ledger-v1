"""Paths, config, database schema and small shared helpers."""
import datetime as _dt
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent

FOLDERS = [
    ("00-inbox", "抓回來的原始資料，檔名含日期"),
    ("10-notes", "你的看球筆記與語音逐字稿"),
    ("20-drafts", "稿件（Markdown，檔頭記錄場次、題目、平台版本）"),
    ("30-published", "已發布版本與各平台待貼稿"),
    ("40-data", "ledger.sqlite、備份、觀賽單資料"),
    ("50-prompts", "提示詞三件套、各平台改寫模板、lint 設定"),
    ("60-assets", "自繪圖卡、站位圖，附素材授權狀態"),
]

PLATFORMS = ["threads", "ig", "fb", "yt", "linkedin", "email", "medium", "vocus"]
PUBLISH_PLATFORMS = ["site"] + PLATFORMS
PILLARS = {
    "reading": ("一檔看懂", "Reading the Game"),
    "ledger": ("球團資產", "The Franchise Ledger"),
    "travel": ("朝聖手冊", "Gameday Travel"),
}
STREAMS = {
    "member": ("會員月費", "Membership"),
    "guide": ("單次專題", "Guides"),
    "b2b": ("企業案", "B2B"),
    "travel": ("旅遊報酬", "Travel"),
    "sponsor": ("贊助", "Sponsorship"),
}
EVENT_TYPES = ["click", "signup", "open", "paid", "cancel"]

DEFAULT_CONFIG = {
    "_note": "base_url 與 contact_email 是占位值 PLACEHOLDER，上線前請改成你自己的。",
    "brand_zh": "球場帳本",
    "brand_en": "Gridiron Ledger",
    "tagline_zh": "用投資人與領隊的眼睛看 NFL",
    "tagline_en": "The NFL, read by an investor and a tour leader.",
    "base_url": "https://example.com",
    "contact_email": "hello@example.com",
    "author": "",
    "benchmark_hourly_ntd": 400,
    "tools_monthly_ntd": 1500,
    "fact_stale_days": 180,
    "subscribe": {
        "mode": "waitlist",
        "_modes": "waitlist（可用）| vocus（填 vocus_url 後為外連）| ecpay、newebpay（v1 未串接 NOT CONNECTED）",
        "vocus_url": "",
    },
    "events_endpoint": "",
    "rules": {
        "_note": "以下門檻是起始假設，不是量測值；請依實際資料調整。",
        "min_sample": 30,
        "window_days": 28,
        "click_to_signup_min": 0.03,
        "signup_to_open_min": 0.30,
        "open_to_paid_min": 0.02,
        "cancel_to_paid_max": 0.30,
        "platform_hours_min": 2.0,
        "platform_signups_per_hour_min": 1.0,
        "inquiry_pillar_share_min": 0.5,
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams(
  team TEXT PRIMARY KEY,
  valuation_usd_b REAL,
  valuation_source TEXT,
  valuation_date TEXT,
  stadium TEXT,
  pe_holders TEXT,
  note TEXT
);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  claim TEXT NOT NULL,
  number REAL,
  unit TEXT NOT NULL DEFAULT '',
  source_url TEXT,
  source_name TEXT,
  retrieved_at TEXT,
  used_in TEXT NOT NULL DEFAULT '',
  corrected_at TEXT,
  previous_number REAL
);
CREATE TABLE IF NOT EXISTS posts(
  content_id TEXT NOT NULL,
  game_id TEXT,
  platform TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL CHECK(status IN ('staged','published','failed')),
  url TEXT,
  published_at TEXT,
  fact_ids TEXT NOT NULL DEFAULT '',
  error TEXT,
  UNIQUE(content_id, platform, version)
);
CREATE TABLE IF NOT EXISTS predictions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id TEXT,
  claim TEXT NOT NULL,
  made_at TEXT NOT NULL,
  outcome TEXT NOT NULL DEFAULT 'open' CHECK(outcome IN ('open','hit','miss','push')),
  checked_at TEXT,
  note TEXT
);
CREATE TABLE IF NOT EXISTS members(
  email_hash TEXT PRIMARY KEY,
  joined_at TEXT,
  first_source TEXT,
  plan TEXT,
  status TEXT
);
CREATE TABLE IF NOT EXISTS costs(
  content_id TEXT PRIMARY KEY,
  hours_research REAL NOT NULL DEFAULT 0,
  hours_write REAL NOT NULL DEFAULT 0,
  hours_edit REAL NOT NULL DEFAULT 0,
  hours_dist REAL NOT NULL DEFAULT 0,
  logged_at TEXT
);
-- 以下是藍圖六張表之外、v1 為了追蹤而加的輔助表
CREATE TABLE IF NOT EXISTS links(
  content_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  url TEXT NOT NULL,
  created_at TEXT,
  UNIQUE(content_id, platform)
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  src TEXT NOT NULL,
  c TEXT NOT NULL,
  event TEXT NOT NULL CHECK(event IN ('click','signup','open','paid','cancel')),
  amount REAL NOT NULL DEFAULT 0,
  batch TEXT
);
CREATE TABLE IF NOT EXISTS imports(
  sha TEXT PRIMARY KEY, filename TEXT, imported_at TEXT, rows INTEGER
);
CREATE TABLE IF NOT EXISTS revenue(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  stream TEXT NOT NULL CHECK(stream IN ('member','guide','b2b','travel','sponsor')),
  amount REAL NOT NULL,
  content_id TEXT,
  note TEXT
);
CREATE TABLE IF NOT EXISTS platform_hours(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL, platform TEXT NOT NULL, hours REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS inquiries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL, pillar TEXT, content_id TEXT, source TEXT, note TEXT
);
"""


class LedgerError(Exception):
    """User-facing error: printed without a traceback, exit code 1."""


def today():
    return os.environ.get("LEDGER_TODAY") or _dt.date.today().isoformat()


def now():
    t = os.environ.get("LEDGER_TODAY")
    if t:
        return t + "T00:00:00"
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def resolve_home(arg=None):
    return Path(arg or os.environ.get("LEDGER_HOME") or PKG_ROOT).resolve()


class Home:
    def __init__(self, path=None):
        self.root = resolve_home(path)

    def __truediv__(self, other):
        return self.root / other

    @property
    def db_path(self):
        return self.root / "40-data" / "ledger.sqlite"

    @property
    def config_path(self):
        return self.root / "ledger.config.json"

    def config(self):
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if self.config_path.exists():
            user = json.loads(self.config_path.read_text(encoding="utf-8"))
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        return cfg

    def connect(self):
        if not self.db_path.exists():
            raise LedgerError("找不到資料庫 %s。請先執行：python3 ledger.py init" % self.db_path)
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def salt(self):
        p = self.root / "40-data" / ".salt"
        if not p.exists():
            p.write_text(secrets.token_hex(16), encoding="utf-8")
        return p.read_text(encoding="utf-8").strip()

    def drafts(self):
        d = self.root / "20-drafts"
        return sorted(p for p in d.glob("*.md") if not p.name.startswith("_")) if d.exists() else []


def init_home(home):
    """Create folders, config and database. Safe to run again."""
    made = []
    for name, desc in FOLDERS:
        d = home / name
        if not d.exists():
            d.mkdir(parents=True)
            made.append(name)
        keep = d / ".gitkeep"
        if not any(d.iterdir()):
            keep.write_text("", encoding="utf-8")
    (home / "reports").mkdir(exist_ok=True)
    (home / "40-data" / "backups").mkdir(exist_ok=True)
    # copy shipped prompts when the home is not the repo itself
    src = PKG_ROOT / "50-prompts"
    dst = home / "50-prompts"
    if src.exists() and src.resolve() != dst.resolve():
        for p in src.rglob("*"):
            if p.is_file():
                t = dst / p.relative_to(src)
                if not t.exists():
                    t.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(p, t)
    if not home.config_path.exists():
        home.config_path.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        made.append("ledger.config.json")
    wl = home / "40-data" / "watchlist.json"
    if not wl.exists():
        shipped = PKG_ROOT / "studio" / "sample" / "watchlist.json"
        if shipped.exists():
            shutil.copyfile(shipped, wl)
    new_db = not home.db_path.exists()
    con = sqlite3.connect(str(home.db_path))
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    home.salt()
    if new_db:
        made.append("40-data/ledger.sqlite")
    return made


def hash_email(email, salt):
    return hashlib.sha256((salt + ":" + email.strip().lower()).encode("utf-8")).hexdigest()


def fmt_num(n):
    """31.0 -> '31', 9.5 -> '9.5'."""
    if n is None:
        return ""
    f = float(n)
    return str(int(f)) if f == int(f) else ("%g" % f)


def ntd(n):
    n = int(round(n))
    return ("-" if n < 0 else "") + "NT$" + format(abs(n), ",")

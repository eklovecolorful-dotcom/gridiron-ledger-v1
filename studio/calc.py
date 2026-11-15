"""Terminal version of the blueprint's revenue calculator (section 4.1)."""
from .core import ntd

SCENARIOS = {
    "保守": dict(mem=25, arpu=185, dig=40, digp=590, b2b=2, b2bp=30000, trip=0, tripp=6000, sp=0, spp=8000, hw=10, ph=25, tool=1500),
    "基準": dict(mem=70, arpu=185, dig=150, digp=590, b2b=6, b2bp=30000, trip=4, tripp=6000, sp=2, spp=8000, hw=14, ph=25, tool=1500),
    "進取": dict(mem=160, arpu=185, dig=400, digp=590, b2b=12, b2bp=30000, trip=10, tripp=6000, sp=6, spp=8000, hw=20, ph=25, tool=1500),
}
ALIASES = {"conservative": "保守", "base": "基準", "stretch": "進取", "c": "保守", "b": "基準", "s": "進取"}
GUIDE_FEE = 0.08
CONTENT_WEEKS = 40
STREAM_LABELS = ["會員月費", "單次專題", "企業案", "旅遊報酬", "贊助"]


def compute(v):
    parts = [v["mem"] * v["arpu"] * 12, v["dig"] * v["digp"] * (1 - GUIDE_FEE), v["b2b"] * v["b2bp"],
             v["trip"] * v["tripp"], v["sp"] * v["spp"]]
    revenue = sum(parts)
    cost = v["tool"] * 12
    hours = v["hw"] * CONTENT_WEEKS + v["b2b"] * v["ph"]
    profit = revenue - cost
    return {"parts": parts, "revenue": revenue, "tool_cost": cost, "profit": profit, "hours": hours,
            "per_hour": (profit / hours) if hours else None}


def render(benchmark=400, overrides=None, only=None):
    lines = ["變現試算 Revenue calculator（規劃假設，不是預測；不含稅、退款、廣告費、開發費）", ""]
    names = [only] if only else list(SCENARIOS)
    for name in names:
        v = dict(SCENARIOS[name])
        v.update(overrides or {})
        r = compute(v)
        lines.append("【%s】 會員 %g 人 × NT$%g × 12、專題 %g 份 × NT$%g（扣 8%% 手續費）、企業案 %g 件、旅遊 %g 團、贊助 %g 檔"
                     % (name, v["mem"], v["arpu"], v["dig"], v["digp"], v["b2b"], v["trip"], v["sp"]))
        for label, p in zip(STREAM_LABELS, r["parts"]):
            share = round(p / r["revenue"] * 100) if r["revenue"] else 0
            lines.append("    %-6s %12s  %3d%%" % (label, ntd(p), share))
        lines.append("    年收入 Revenue        %s" % ntd(r["revenue"]))
        lines.append("    扣工具成本後 Profit    %s" % ntd(r["profit"]))
        lines.append("    總工時 Hours          %s 小時（每週 %g × %d 週 + 企業案 %g × %g）"
                     % (format(int(round(r["hours"])), ","), v["hw"], CONTENT_WEEKS, v["b2b"], v["ph"]))
        if r["per_hour"] is None:
            lines.append("    每工時利潤 Per hour    -")
        else:
            mark = "高於" if r["per_hour"] >= benchmark else "低於"
            lines.append("    每工時利潤 Per hour    %s（%s時薪基準 %s）" % (ntd(r["per_hour"]), mark, ntd(benchmark)))
        lines.append("")
    return "\n".join(lines)

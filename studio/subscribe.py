"""Subscribe / payment adapters for the public site.

Only `waitlist` does real work in v1. The others are documented placeholders:
they never render a checkout form; the site falls back to the waitlist and the
build prints NOT CONNECTED.
"""
from .md import esc


class Adapter:
    name = ""
    connected = False
    label = ""

    def __init__(self, cfg):
        self.cfg = cfg

    def status(self):
        return "%s: %s" % (self.name, "connected" if self.connected else "NOT CONNECTED 未串接")

    def render(self, uid, heading):
        raise NotImplementedError


class Waitlist(Adapter):
    """Working mode: the form opens the visitor's own mail app (mailto).
    You reply by hand and add the address to a CSV, then `ledger member import`."""
    name = "waitlist"
    connected = True
    label = "mailto / CSV 候補名單"

    def render(self, uid, heading):
        to = esc(self.cfg["contact_email"])
        return (
            '<form class="signup box" data-signup data-to="%s" action="mailto:%s" method="post" enctype="text/plain">'
            '<h3>%s</h3>'
            '<label for="em-%s" class="note">Email <span lang="en">· weekly letter, free</span></label>'
            '<div class="row"><input id="em-%s" type="email" name="email" required autocomplete="email" placeholder="you@example.com">'
            '<button class="b primary" type="submit">加入名單</button></div>'
            '<p data-status role="status" aria-live="polite"></p>'
            '<p class="note">按下後會開啟你的郵件程式，寄出一封訂閱信，由作者人工回覆確認。本頁不收款，也不會自動寄信。'
            '<span lang="en"> This opens your mail app; nothing is charged or sent automatically.</span></p>'
            '</form>') % (to, to, esc(heading), uid, uid)


class Vocus(Adapter):
    """方格子沙龍: a plain outbound link to your hosted page. Connected only when
    subscribe.vocus_url is filled in; payment happens on vocus, not here."""
    name = "vocus"
    label = "方格子沙龍（外連）"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.url = (cfg["subscribe"].get("vocus_url") or "").strip()
        self.connected = self.url.startswith("https://")

    def render(self, uid, heading):
        return ('<div class="signup box"><h3>%s</h3><p>訂閱與付款在方格子進行，本站不經手款項。</p>'
                '<p><a class="b primary" href="%s" rel="noopener">前往方格子沙龍</a></p></div>') % (esc(heading), esc(self.url))


class ECPay(Adapter):
    """綠界 ECPay — PLACEHOLDER, NOT CONNECTED.
    A real integration needs a server that signs each order (CheckMacValue) and
    receives the payment callback; a static site cannot do that safely."""
    name = "ecpay"
    label = "綠界 ECPay"


class NewebPay(Adapter):
    """藍新 NewebPay — PLACEHOLDER, NOT CONNECTED.
    Needs server-side AES/SHA signing (TradeInfo / TradeSha) and a notify URL."""
    name = "newebpay"
    label = "藍新 NewebPay"


ADAPTERS = {a.name: a for a in (Waitlist, Vocus, ECPay, NewebPay)}


def pick(cfg):
    """Return (adapter_to_render, warning_or_None). Never returns an unconnected adapter."""
    mode = cfg["subscribe"].get("mode", "waitlist")
    cls = ADAPTERS.get(mode)
    if cls is None:
        return Waitlist(cfg), "subscribe.mode「%s」不存在，改用 waitlist。" % mode
    a = cls(cfg)
    if not a.connected:
        return Waitlist(cfg), "%s（%s）NOT CONNECTED 未串接：網站改用 waitlist，不會顯示任何結帳畫面。" % (a.name, a.label)
    return a, None

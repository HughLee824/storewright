from __future__ import annotations

from shop_scout.domain.enums import PageKind

LOGIN_URL_MARKERS = (
    "login.taobao.com",
    "login.tmall.com",
    "passport.taobao.com",
    "/member/login",
    "/login.htm",
)
VERIFY_URL_MARKERS = ("/punish", "/challenge", "/verify", "captcha")
VERIFY_TEXT_MARKERS = ("安全验证", "请完成验证", "滑块验证", "账号异常")
BLOCKED_TEXT_MARKERS = ("访问被拒绝", "操作过于频繁", "流量异常", "稍后再试")


def classify_page_state(url: str, title: str, html: str) -> PageKind:
    lowered_url = url.lower()
    lowered_html = html.lower()
    if any(marker in lowered_url for marker in LOGIN_URL_MARKERS) or (
        'type="password"' in lowered_html and any(word in title for word in ("登录", "Login"))
    ):
        return PageKind.LOGIN
    if any(marker in lowered_url for marker in VERIFY_URL_MARKERS) or any(
        marker in html for marker in VERIFY_TEXT_MARKERS
    ):
        return PageKind.VERIFICATION
    if any(marker in html for marker in BLOCKED_TEXT_MARKERS):
        return PageKind.BLOCKED
    distinct_links = set()
    for fragment in lowered_html.split("href=")[1:]:
        value = fragment[:200]
        if "item.htm" in value and "id=" in value:
            distinct_links.add(value.split("id=", 1)[1].split("&", 1)[0].split('"', 1)[0])
    if len(distinct_links) >= 2:
        return PageKind.PRODUCT_LISTING
    if "item.htm" in lowered_url and "id=" in lowered_url:
        return PageKind.PRODUCT_DETAIL
    return PageKind.UNKNOWN

from storewright_catalog_scout.browser.page_state import classify_page_state
from storewright_catalog_scout.domain.enums import PageKind


def test_login_verification_listing_and_detail_states() -> None:
    assert classify_page_state("https://login.taobao.com/", "", "") == PageKind.LOGIN
    assert classify_page_state("https://x/", "请登录淘宝", "") == PageKind.LOGIN
    assert classify_page_state("https://x/", "", "请完成验证") == PageKind.VERIFICATION
    html = '<a href="item.htm?id=1">a</a><a href="item.htm?id=2">b</a>'
    assert classify_page_state("https://x/", "", html) == PageKind.PRODUCT_LISTING
    assert (
        classify_page_state("https://item.taobao.com/item.htm?id=1", "", "")
        == PageKind.PRODUCT_DETAIL
    )
    assert classify_page_state("https://x/", "", "商品描述提到验证") == PageKind.UNKNOWN

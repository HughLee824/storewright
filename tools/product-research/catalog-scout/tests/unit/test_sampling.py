from storewright_catalog_scout.domain.models import ProductRef
from storewright_catalog_scout.sampling.sampler import order_products


def test_product_order_is_stable_and_complete() -> None:
    products = [
        ProductRef(
            external_item_id=str(index),
            canonical_url=f"https://item.taobao.com/item.htm?id={index}",
            source_position=index,
        )
        for index in range(20)
    ]
    first_seed, first = order_products(products, 42, "shop:1")
    second_seed, second = order_products(list(reversed(products)), 42, "shop:1")
    assert first_seed == second_seed
    assert [item.external_item_id for item in first] == [item.external_item_id for item in second]
    assert {item.external_item_id for item in first} == {str(index) for index in range(20)}

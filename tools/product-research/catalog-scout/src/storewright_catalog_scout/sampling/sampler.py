import hashlib
import random

from storewright_catalog_scout.domain.models import ProductRef


def derive_order_seed(run_seed: int, shop_canonical_key: str) -> int:
    material = f"{run_seed}:{shop_canonical_key}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def order_products(
    products: list[ProductRef], run_seed: int, shop_canonical_key: str
) -> tuple[int, list[ProductRef]]:
    """Return a stable shuffled order so early decisions are not listing-order biased."""
    seed = derive_order_seed(run_seed, shop_canonical_key)
    ordered = sorted(products, key=lambda item: (item.external_item_id, item.canonical_url))
    random.Random(seed).shuffle(ordered)
    return seed, ordered

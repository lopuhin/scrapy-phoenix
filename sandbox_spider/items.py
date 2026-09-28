"""Hard requirements on delivered items: checked before anything is yielded.

This is part of the spider's intent, not its implementation: repairs may add
layout variants but may not edit this file.
"""

from decimal import Decimal, InvalidOperation

from zyte_common_items import Product, ProductNavigation

from selfheal.dispatch import ItemCheckError


def check_product(item: Product) -> None:
    for name in ("url", "name", "price", "currency", "availability"):
        if not getattr(item, name):
            raise ItemCheckError(name, "missing")
    try:
        price = Decimal(item.price)
    except InvalidOperation:
        raise ItemCheckError("price", f"not a number: {item.price!r}") from None
    if price <= 0:
        raise ItemCheckError("price", f"not positive: {item.price!r}")
    if item.regularPrice is not None and Decimal(item.regularPrice) < price:
        raise ItemCheckError("regularPrice", "lower than price")
    if len(item.currency) != 3 or not item.currency.isupper():
        raise ItemCheckError("currency", f"not an ISO 4217 code: {item.currency!r}")
    if item.availability not in ("InStock", "OutOfStock"):
        raise ItemCheckError("availability", f"unexpected: {item.availability!r}")


def check_navigation(item: ProductNavigation) -> None:
    if not item.items and not item.subCategories:
        raise ItemCheckError("items", "dead end: no products and no subcategories")

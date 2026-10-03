"""Hard requirements on delivered items (see README.md)."""

from decimal import Decimal, InvalidOperation

from zyte_common_items import Product, ProductNavigation

from selfheal.dispatch import ItemCheckError


def check_product(item: Product) -> None:
    for name in ("url", "name", "price", "currency", "availability", "sku"):
        if not getattr(item, name):
            raise ItemCheckError(name, "missing")
    try:
        if Decimal(item.price) <= 0:
            raise ItemCheckError("price", f"not positive: {item.price!r}")
    except InvalidOperation:
        raise ItemCheckError("price", f"not a number: {item.price!r}") from None
    if item.currency != "GBP":
        raise ItemCheckError("currency", f"expected GBP, got {item.currency!r}")


def check_navigation(item: ProductNavigation) -> None:
    if not item.items and not item.subCategories:
        raise ItemCheckError("items", "dead end: no products and no subcategories")

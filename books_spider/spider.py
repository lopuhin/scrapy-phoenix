import scrapy
from scrapy.http import Response
from zyte_common_items import Product, ProductNavigation

from selfheal.spider import SelfHealingSpider

from .items import check_navigation, check_product


class BooksSpider(SelfHealingSpider):
    """Every book on books.toscrape.com.

    Navigation is explicit: every listing page goes to a navigation variant,
    whose ``subCategories``, ``items`` and ``nextPage`` are followed. The
    current page travels along ``nextPage`` as ``previous`` so the next page
    can be checked for progress (see ``selfheal.dispatch.check_progress``).
    """

    name = "books"
    start_urls = ["https://books.toscrape.com/"]
    allowed_domains = ["books.toscrape.com"]
    variants_package = "books_spider.variants"
    item_checks = {Product: check_product, ProductNavigation: check_navigation}
    custom_settings = {"CONCURRENT_REQUESTS": 8}

    async def start(self):
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse_navigation)

    async def parse_navigation(self, response: Response, previous: ProductNavigation | None = None):
        nav = await self.extract(ProductNavigation, response, previous)
        if nav is None:
            return
        for request in nav.subCategories or []:
            yield response.follow(request.url, self.parse_navigation)
        for request in nav.items or []:
            yield response.follow(request.url, self.parse_product)
        if nav.nextPage:
            yield response.follow(
                nav.nextPage.url, self.parse_navigation, cb_kwargs={"previous": nav}
            )

    async def parse_product(self, response: Response):
        product = await self.extract(Product, response)
        if product is not None:
            yield product

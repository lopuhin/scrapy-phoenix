from urllib.parse import urlparse

import scrapy
from scrapy.http import Response
from zyte_common_items import Product, ProductNavigation

from sandbox_spider.items import check_navigation, check_product
from selfheal.spider import SelfHealingSpider


class SandboxModernSpider(SelfHealingSpider):
    """The sandbox store, for a site that has always had the ``modern`` design.

    Navigation is explicit: every listing page goes to a navigation variant,
    whose ``subCategories``, ``items`` and ``nextPage`` are followed. The
    current page travels along ``nextPage`` as ``previous`` so the next page
    can be checked for progress (see ``selfheal.dispatch.check_progress``).
    """

    name = "sandbox_modern"
    variants_package = "sandbox_modern.variants"
    item_checks = {Product: check_product, ProductNavigation: check_navigation}

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.start_urls = [crawler.settings["SANDBOX_URL"]]
        spider.allowed_domains = [urlparse(spider.start_urls[0]).hostname]
        return spider

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

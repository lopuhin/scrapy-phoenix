from urllib.parse import urlparse

import scrapy
from scrapy.http import Response
from zyte_common_items import Product, ProductNavigation

from selfheal.spider import SelfHealingSpider

from .items import check_navigation, check_product


class SandboxStoreSpider(SelfHealingSpider):
    name = "sandbox_store"
    variants_package = "sandbox_spider.variants"
    item_checks = {Product: check_product, ProductNavigation: check_navigation}

    async def start(self):
        url = self.settings["SANDBOX_URL"]
        self.allowed_domains = [urlparse(url).netloc.split(":")[0]]
        yield scrapy.Request(url, callback=self.parse_navigation)

    async def parse_navigation(self, response: Response):
        nav = await self.extract(ProductNavigation, response)
        if nav is None:
            return
        for request in nav.subCategories or []:
            yield response.follow(request.url, self.parse_navigation)
        for request in nav.items or []:
            yield response.follow(request.url, self.parse_product)
        if nav.nextPage:
            yield response.follow(nav.nextPage.url, self.parse_navigation)

    async def parse_product(self, response: Response):
        product = await self.extract(Product, response)
        if product is not None:
            yield product

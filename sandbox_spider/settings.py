import os

BOT_NAME = "sandbox_spider"
SPIDER_MODULES = [
    "sandbox_spider.spider",
    "sandbox_modern.spider",
    "sandbox_scroll.spider",
    "books_spider.spider",
]

# Base URL of a locally running zyte-monitoring-sandbox (see README.md).
SANDBOX_URL = "http://127.0.0.1:8765/sandbox-store/"

ROBOTSTXT_OBEY = False
CONCURRENT_REQUESTS = 16
AUTOTHROTTLE_ENABLED = False
LOG_LEVEL = "INFO"

# The healer (selfheal.healer) is loaded always but stays off unless
# SELFHEAL_ENABLED is set, e.g. `scrapy crawl sandbox_store -s SELFHEAL_ENABLED=1`.
EXTENSIONS = {"selfheal.healer.Healer": 0}
# The Scrapy Cloud image sets bypassPermissions (see Dockerfile).
SELFHEAL_PERMISSION_MODE = os.environ.get("SELFHEAL_PERMISSION_MODE", "acceptEdits")

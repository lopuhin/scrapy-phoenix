BOT_NAME = "sandbox_spider"
SPIDER_MODULES = ["sandbox_spider.spider"]

# Base URL of a locally running zyte-monitoring-sandbox (see README.md).
SANDBOX_URL = "http://127.0.0.1:8765/sandbox-store/"

ROBOTSTXT_OBEY = False
CONCURRENT_REQUESTS = 16
AUTOTHROTTLE_ENABLED = False
LOG_LEVEL = "INFO"

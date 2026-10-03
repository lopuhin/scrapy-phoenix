import os

from pydantic_settings import BaseSettings

ENV_FILE = os.getenv("SETTINGS_ENV_FILE", "settings.env")


class Settings(BaseSettings):
    PROJECT_NAME: str = "Zyte Monitoring Sandbox"

    # Layout configuration
    # Options: "layout_default", "layout_modern", "layout_load_more", "layout_infinite_scroll", "layout_variant_dom_change", "layout_hidden_price", "layout_no_price"
    ACTIVE_LAYOUT: str = "layout_default"

    # A/B Testing Configuration
    # 0.0 to 1.0 (e.g. 0.2 means 20% of requests use the alternate layout)
    AB_TEST_RATIO: float = 0.0
    # The layout to serve for the B group
    AB_TEST_LAYOUT: str = "layout_modern"
    # Target: "products", "categories", "all"
    AB_TEST_TARGET: str = "all"
    # Seed for deterministic assignment.
    AB_TEST_SEED: int = 123

    # Ban Testing Configuration
    # 0.0 to 1.0 (e.g. 0.1 means 10% of requests are banned)
    BAN_RATIO: float = 0.0
    # HTTP Status Code for the ban response
    BAN_STATUS_CODE: int = 403
    # Target: "products", "categories", "all"
    BAN_TARGET: str = "all"
    # Seed for deterministic assignment.
    BAN_SEED: int = 456

    # Data Generation Configuration
    # Ratio of products that are out of stock (0.0 - 1.0)
    OUT_OF_STOCK_RATIO: float = 0.10
    OUT_OF_STOCK_SEED: int = 789

    # Ratio of products that have discounts (0.0 - 1.0)
    DISCOUNT_RATIO: float = 0.20
    DISCOUNT_SEED: int = 101112

    # Ratio of products that have ratings (0.0 - 1.0)
    # If a product has no rating, rating=0.0 and reviews_count=0
    HAS_RATING_RATIO: float = 0.80
    HAS_RATING_SEED: int = 131415

    # Scale product count (1.0 = normal, 0.5 = half products, 2.0 = double)
    PRODUCT_COUNT_SCALE: float = 1.0

    # Scale product count for the Books category ONLY (composes with
    # PRODUCT_COUNT_SCALE). Books carry Publisher/Author attributes and never a
    # Brand, so raising this deterministically lowers brand field-coverage across
    # the catalog — the data-mix break lever used by the self-healing use-case
    # tests (a break no layout knob can produce).
    BOOKS_COUNT_SCALE: float = 1.0

    # Base seed for data generation
    DATA_GENERATION_SEED: int = 42

    # Pagination
    ITEMS_PER_PAGE: int = 12

    class Config:
        env_file = ENV_FILE


settings = Settings()

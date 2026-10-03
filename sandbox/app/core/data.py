from faker import Faker
from typing import List, Dict, Optional
from app.core.models import Product, Category, Variant
from app.core.config import settings
import random
import zlib

# Use random.Random instance for data generation to avoid global state issues
# Seed logic is handled by DataManager __init__ but we need a base instance
gen_random = random.Random()
fake = Faker()

# Configuration for realistic data
CATEGORY_DATA = {
    "Electronics": {
        "subcategories": [
            "Smartphones",
            "Laptops",
            "Headphones",
            "Cameras",
            "Smart Watches",
        ],
        "attributes": {
            "Brand": ["Sony", "Samsung", "Apple", "Dell", "Canon", "Nikon", "Bose"],
            "Color": ["Black", "Silver", "White", "Midnight Blue"],
            "Warranty": ["1 Year", "2 Years", "Lifetime Limited"],
            "Condition": ["New", "Refurbished"],
        },
        "price_range": (100.0, 2000.0),
        "desc_templates": [
            "Experience the ultimate performance with the {name}. Featuring a sleek {Color} finish and cutting-edge technology, it's designed to keep up with your busy lifestyle. Backed by a {Warranty} warranty.",
            "Upgrade your tech game with {Brand}'s latest {sub_cat_singular}. Whether for work or play, the {name} delivers stunning visuals and reliable speed. Available now in {Color}.",
            "The {name} by {Brand} defines innovation. In pristine {Condition} condition, this device offers premium features at a competitive price. Perfect for enthusiasts.",
        ],
        "variant_config": {
            "Smartphones": {
                "options": {
                    "Storage": ["64GB", "128GB", "256GB"],
                    "Color": ["Black", "White", "Gold"],
                },
                "price_mod": 50,
            },
            "Laptops": {
                "options": {
                    "RAM": ["8GB", "16GB", "32GB"],
                    "Storage": ["256GB SSD", "512GB SSD"],
                },
                "price_mod": 150,
            },
        },
    },
    "Clothing": {
        "subcategories": [
            "Men's T-Shirts",
            "Women's Dresses",
            "Running Shoes",
            "Jackets",
            "Accessories",
        ],
        "attributes": {
            "Size": ["XS", "S", "M", "L", "XL", "XXL"],
            "Material": ["Cotton", "Polyester", "Wool", "Leather", "Denim"],
            "Gender": ["Men", "Women", "Unisex"],
            "Brand": ["Nike", "Adidas", "Zara", "H&M", "Levi's"],
        },
        "price_range": (15.0, 200.0),
        "desc_templates": [
            "Step out in style with the {name}. Made from high-quality {Material}, this {sub_cat_singular} ensures comfort and durability. Perfect for {Gender} who appreciate fashion.",
            "Discover the new collection from {Brand}. The {name} combines classic design with modern trends. Available in size {Size}, it's a must-have for your wardrobe.",
            "Stay comfortable all day in this premium {Material} {sub_cat_singular}. The {name} offers a perfect fit and breathable fabric, ideal for any occasion.",
        ],
        "variant_config": {
            "Men's T-Shirts": {
                "options": {
                    "Size": ["S", "M", "L", "XL"],
                    "Color": ["Red", "Blue", "Black"],
                },
                "price_mod": 0,
            },
            "Women's Dresses": {
                "options": {
                    "Size": ["XS", "S", "M", "L"],
                    "Color": ["Red", "Black", "Floral"],
                },
                "price_mod": 0,
            },
            "Running Shoes": {
                "options": {
                    "Size": ["7", "8", "9", "10", "11"],
                    "Color": ["White", "Black", "Neon"],
                },
                "price_mod": 0,
            },
        },
    },
    "Home & Garden": {
        "subcategories": [
            "Furniture",
            "Kitchenware",
            "Bedding",
            "Gardening Tools",
            "Lighting",
        ],
        "attributes": {
            "Material": ["Wood", "Stainless Steel", "Ceramic", "Plastic", "Glass"],
            "Color": ["White", "Beige", "Green", "Brown", "Grey"],
            "Dimensions": ["Standard", "Large", "Compact"],
        },
        "price_range": (20.0, 800.0),
        "desc_templates": [
            "Transform your living space with the {name}. Crafted from durable {Material}, this {Color} piece adds a touch of elegance to any room. Dimensions: {Dimensions}.",
            "Practicality meets style in the {name}. Designed for modern homes, this {sub_cat_singular} is made of high-grade {Material} and built to last.",
            "Enhance your home with the {name}. Its timeless {Color} finish and sturdy construction make it a favorite among interior designers.",
        ],
    },
    "Books": {
        "subcategories": [
            "Fiction",
            "Science & Technology",
            "History",
            "Biographies",
            "Comics",
        ],
        "attributes": {
            "Author": lambda: fake.name(),
            "Publisher": lambda: fake.company(),
            "Format": ["Hardcover", "Paperback", "E-book"],
            "Language": ["English", "Spanish", "French"],
        },
        "price_range": (10.0, 50.0),
        "desc_templates": [
            "Dive into the captivating world of '{name}'. Written by {Author} and published by {Publisher}, this {Format} edition is a masterpiece of storytelling.",
            "A must-read for enthusiasts, '{name}' explores complex themes with depth and clarity. Available in {Language}, it is a valuable addition to any library.",
            "Acclaimed author {Author} returns with '{name}', a gripping tale that will keep you on the edge of your seat. Get your {Format} copy today.",
        ],
    },
}


class DataManager:
    def __init__(self):
        self.reload()

    def reload(self):
        self.categories: Dict[str, Category] = {}
        self.products: Dict[str, Product] = {}

        # Determine seeds once per manager instance
        self.data_seed = settings.DATA_GENERATION_SEED
        self.stock_seed = settings.OUT_OF_STOCK_SEED
        self.discount_seed = settings.DISCOUNT_SEED
        self.rating_seed = settings.HAS_RATING_SEED

        # Seed the generators
        gen_random.seed(self.data_seed)
        Faker.seed(self.data_seed)

        self._generate_data()

    def _should_apply_feature(self, entity_id: str, seed: int, ratio: float) -> bool:
        if ratio <= 0:
            return False
        combined_id = f"{entity_id}-{seed}"
        hash_val = zlib.crc32(combined_id.encode()) & 0xFFFFFFFF
        calculated_ratio = hash_val / 0xFFFFFFFF
        return calculated_ratio < ratio

    def _generate_data(self):
        # Generate Categories
        for i, (main_name, data) in enumerate(CATEGORY_DATA.items()):
            cat_id = f"cat_{i}"
            cat = Category(
                id=cat_id, name=main_name, slug=fake.slug(main_name), subcategories=[]
            )
            self.categories[cat_id] = cat

            # Subcategories
            for j, sub_name in enumerate(data["subcategories"]):
                sub_id = f"{cat_id}_sub_{j}"
                sub_cat = Category(
                    id=sub_id, name=sub_name, slug=fake.slug(sub_name), parent_id=cat_id
                )
                cat.subcategories.append(sub_cat)
                self.categories[sub_id] = sub_cat

                # Generate Products for this subcategory
                self._generate_products(sub_id, main_name, sub_name, data)

    def _generate_products(
        self, category_id: str, main_cat_name: str, sub_cat_name: str, data: dict
    ):
        # Determine number of products
        # Base count between 15 and 40
        base_count = gen_random.randint(15, 40)
        # Apply scaling factors from settings (Books get their own multiplier —
        # they carry Publisher instead of Brand, so their share drives brand coverage)
        scale = settings.PRODUCT_COUNT_SCALE
        if main_cat_name == "Books":
            scale *= settings.BOOKS_COUNT_SCALE
        count = int(base_count * scale)
        # Ensure at least 1 product if scale > 0
        if count < 1 and scale > 0:
            count = 1

        attr_config = data["attributes"]
        price_min, price_max = data["price_range"]
        desc_templates = data.get("desc_templates", ["A great product named {name}."])
        variant_config_map = data.get("variant_config", {})

        for _ in range(count):
            p_id = fake.uuid4()

            # Generate Attributes
            attributes = {}
            brand_name = None

            for key, values in attr_config.items():
                if callable(values):
                    attributes[key] = values()
                else:
                    attributes[key] = gen_random.choice(values)
                    if key == "Brand":
                        brand_name = attributes[key]

            # Generate Name
            adjective = fake.word().title()

            if main_cat_name == "Books":
                name = fake.catch_phrase().title()
                sub_cat_singular = "Book"
            else:
                prefix = brand_name if brand_name else fake.word().title()
                base_noun = sub_cat_name.split()[-1]
                if base_noun.endswith("s") and not base_noun.endswith("ss"):
                    base_noun = base_noun[:-1]
                sub_cat_singular = base_noun
                name = f"{prefix} {adjective} {base_noun}"

            price = round(gen_random.uniform(price_min, price_max) * settings.PRICE_SCALE, 2)
            original_price = None

            # Generate Rating Logic (Seeded)
            if self._should_apply_feature(
                p_id, self.rating_seed, settings.HAS_RATING_RATIO
            ):
                rating = round(gen_random.uniform(1.0, 5.0), 1)
                reviews_count = gen_random.randint(1, 500)
            else:
                rating = 0.0
                reviews_count = 0

            # Discount Logic (Seeded)
            if self._should_apply_feature(
                p_id, self.discount_seed, settings.DISCOUNT_RATIO
            ):
                original_price = price
                price = round(original_price * gen_random.uniform(0.7, 0.95), 2)

            # Stock Logic (Seeded)
            is_fully_out_of_stock = self._should_apply_feature(
                p_id, self.stock_seed, settings.OUT_OF_STOCK_RATIO
            )

            img_text = f"{name.split()[0]}+{name.split()[-1]}"

            template = gen_random.choice(desc_templates)
            description = template.format(
                name=name, sub_cat_singular=sub_cat_singular, **attributes
            )

            product_variants = []

            # Generate Variants if applicable (40% chance)
            if sub_cat_name in variant_config_map and gen_random.random() < 0.4:
                v_conf = variant_config_map[sub_cat_name]
                options = v_conf["options"]
                price_mod_base = v_conf["price_mod"]

                # Create combinatorial variants
                import itertools

                keys = list(options.keys())
                values_list = [options[k] for k in keys]

                for combo in itertools.product(*values_list):
                    v_attrs = dict(zip(keys, combo))
                    v_name_suffix = " ".join(combo)

                    # Base price for variant
                    v_base_price = round(
                        price
                        + (
                            price_mod_base * gen_random.random()
                            if price_mod_base > 0
                            else 0
                        ),
                        2,
                    )
                    v_price = v_base_price
                    v_original_price = None

                    # Variant Discount Logic (Seeded per variant)
                    variant_id = fake.uuid4()
                    if self._should_apply_feature(
                        variant_id, self.discount_seed, settings.DISCOUNT_RATIO
                    ):
                        v_original_price = v_base_price
                        v_price = round(
                            v_original_price * gen_random.uniform(0.7, 0.95), 2
                        )

                    # Variant Stock Logic (Seeded per variant)
                    v_in_stock = True
                    if is_fully_out_of_stock:
                        v_in_stock = False
                    else:
                        if self._should_apply_feature(
                            variant_id, self.stock_seed, settings.OUT_OF_STOCK_RATIO
                        ):
                            v_in_stock = False

                    product_variants.append(
                        Variant(
                            id=variant_id,
                            name=f"{name} - {v_name_suffix}",
                            price=v_price,
                            original_price=v_original_price,
                            in_stock=v_in_stock,
                            sku=fake.ean13(),
                            attributes=v_attrs,
                            image_url=f"https://placehold.co/300x300?text={v_name_suffix.replace(' ', '+')}",
                        )
                    )

                # Update main product price to reflect "from X" (lowest variant price)
                # If variants have discounts, this will show the lowest discounted price.
                if product_variants:
                    min_v_price = min(v.price for v in product_variants)
                    # Find if this lowest price is discounted
                    min_v = next(v for v in product_variants if v.price == min_v_price)

                    price = min_v.price
                    original_price = (
                        min_v.original_price
                    )  # Could be None if the cheapest variant isn't discounted

                    # Update attributes to list all available options
                    for key in options.keys():
                        # Remove singular attribute if it exists (e.g. "Color": "Black")
                        if key in attributes:
                            del attributes[key]

                        # Add plural attribute with all options (e.g. "Colors": "Black, White")
                        plural_key = key + "s"
                        attributes[plural_key] = ", ".join(options[key])

            product = Product(
                id=p_id,
                name=name,
                slug=fake.slug(name),
                price=price,
                original_price=original_price,
                in_stock=not is_fully_out_of_stock,
                rating=rating,
                reviews_count=reviews_count,
                currency="USD",
                description=description,
                category_id=category_id,
                image_url=f"https://placehold.co/300x300?text={img_text}",
                attributes=attributes,
                variants=product_variants,
            )
            self.products[p_id] = product

    def get_categories(self) -> List[Category]:
        return [c for c in self.categories.values() if "sub" not in c.id]

    def get_category(self, category_id: str) -> Optional[Category]:
        return self.categories.get(category_id)

    def get_products_by_category(
        self, category_id: str, page: int = 1, per_page: int = 12
    ) -> tuple[List[Product], int]:
        filtered = [p for p in self.products.values() if p.category_id == category_id]
        total_items = len(filtered)
        start = (page - 1) * per_page
        end = start + per_page
        return filtered[start:end], total_items

    def get_product(self, product_id: str) -> Optional[Product]:
        return self.products.get(product_id)


data_manager = DataManager()

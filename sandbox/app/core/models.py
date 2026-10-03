from pydantic import BaseModel
from typing import List, Optional


class Category(BaseModel):
    id: str
    name: str
    slug: str
    parent_id: Optional[str] = None
    subcategories: List["Category"] = []


class Variant(BaseModel):
    id: str
    name: str
    price: float
    original_price: Optional[float] = None
    in_stock: bool = True
    sku: str
    attributes: dict
    image_url: Optional[str] = None


class Product(BaseModel):
    id: str
    name: str
    slug: str
    price: float
    original_price: Optional[float] = None
    in_stock: bool = True
    rating: float = 0.0
    reviews_count: int = 0
    currency: str
    description: str
    category_id: str
    image_url: str
    attributes: dict = {}
    variants: List[Variant] = []


Category.model_rebuild()

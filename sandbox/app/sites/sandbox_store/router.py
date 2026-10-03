from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.templating import Jinja2Templates
from app.core.data import data_manager
from app.core.config import settings
import math
import zlib

router = APIRouter()

# Seeds from config
AB_SESSION_SEED = settings.AB_TEST_SEED
BAN_SESSION_SEED = settings.BAN_SEED

templates = Jinja2Templates(directory="app/templates")


def should_ban(entity_id: str, entity_type: str) -> bool:
    if settings.BAN_RATIO > 0:
        if settings.BAN_TARGET == "all" or settings.BAN_TARGET == entity_type:
            # Hash logic, same as A/B testing but using a distinct prefix and separate seed
            combined_id = f"BAN-{entity_id}-{BAN_SESSION_SEED}"
            hash_val = zlib.crc32(combined_id.encode()) & 0xFFFFFFFF
            ratio = hash_val / 0xFFFFFFFF

            if ratio < settings.BAN_RATIO:
                return True
    return False


def get_layout(entity_id: str = None, entity_type: str = None):
    # Default layout
    layout = settings.ACTIVE_LAYOUT

    # Check if A/B testing is enabled
    if settings.AB_TEST_RATIO > 0:
        # Check target
        if settings.AB_TEST_TARGET == "all" or settings.AB_TEST_TARGET == entity_type:
            # Deterministic hash of the ID + Seed
            if entity_id:
                # Combine ID and Seed for run-specific consistency
                combined_id = f"{entity_id}-{AB_SESSION_SEED}"
                hash_val = zlib.crc32(combined_id.encode()) & 0xFFFFFFFF
                ratio = hash_val / 0xFFFFFFFF

                if ratio < settings.AB_TEST_RATIO:
                    layout = settings.AB_TEST_LAYOUT

    return layout


def get_template_path(template_name: str, layout: str = None):
    if not layout:
        layout = settings.ACTIVE_LAYOUT
    return f"sandbox_store/{layout}/{template_name}"


@router.get("/")
async def home(request: Request):
    categories = data_manager.get_categories()
    return templates.TemplateResponse(
        get_template_path("index.html"), {"request": request, "categories": categories}
    )


@router.get("/partials/products")
async def get_products_partial(
    request: Request, category_id: str, page: int = Query(1, ge=1)
):
    # Check Ban Logic
    if should_ban(category_id, "categories"):
        return templates.TemplateResponse(
            "ban.html",
            {"request": request, "status_code": settings.BAN_STATUS_CODE},
            status_code=settings.BAN_STATUS_CODE,
        )

    category = data_manager.get_category(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    products, total_count = data_manager.get_products_by_category(
        category_id, page=page, per_page=settings.ITEMS_PER_PAGE
    )

    return templates.TemplateResponse(
        "sandbox_store/partials/product_cards.html",
        {
            "request": request,
            "products": products,
        },
    )


@router.get("/category/{category_id}")
async def category_detail(
    request: Request, category_id: str, page: int = Query(1, ge=1)
):
    # Check Ban Logic
    if should_ban(category_id, "categories"):
        return templates.TemplateResponse(
            "ban.html",
            {"request": request, "status_code": settings.BAN_STATUS_CODE},
            status_code=settings.BAN_STATUS_CODE,
        )

    category = data_manager.get_category(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    parent_category = None
    if category.parent_id:
        parent_category = data_manager.get_category(category.parent_id)

    products, total_count = data_manager.get_products_by_category(
        category_id, page=page, per_page=settings.ITEMS_PER_PAGE
    )

    total_pages = math.ceil(total_count / settings.ITEMS_PER_PAGE)

    # Determine layout
    layout = get_layout(category_id, "categories")

    # Enforce page 1 for load_more and infinite_scroll layouts
    # This forces the user (or spider) to use the partials endpoint for subsequent pages
    if layout in ["layout_load_more", "layout_infinite_scroll"] and page > 1:
        # We could redirect, or just render page 1. Rendering page 1 mimics a "broken" pagination
        # where the URL parameter is ignored.
        products, _ = data_manager.get_products_by_category(
            category_id, page=1, per_page=settings.ITEMS_PER_PAGE
        )
        # Update page context to 1 so the template knows
        page = 1

    return templates.TemplateResponse(
        get_template_path("listing.html", layout),
        {
            "request": request,
            "category": category,
            "parent_category": parent_category,
            "products": products,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
        },
    )


@router.get("/product/{product_id}")
async def product_detail(request: Request, product_id: str):
    # Check Ban Logic
    if should_ban(product_id, "products"):
        return templates.TemplateResponse(
            "ban.html",
            {"request": request, "status_code": settings.BAN_STATUS_CODE},
            status_code=settings.BAN_STATUS_CODE,
        )

    product = data_manager.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    category = data_manager.get_category(product.category_id)
    parent_category = None
    if category and category.parent_id:
        parent_category = data_manager.get_category(category.parent_id)

    variant_options = {}
    if product.variants:
        # Extract all unique keys and values from variants
        for variant in product.variants:
            for key, value in variant.attributes.items():
                if key not in variant_options:
                    variant_options[key] = set()
                variant_options[key].add(value)

        # Convert sets to sorted lists for consistent rendering
        for key in variant_options:
            variant_options[key] = sorted(list(variant_options[key]))

    # Determine layout
    layout = get_layout(product_id, "products")

    return templates.TemplateResponse(
        get_template_path("detail.html", layout),
        {
            "request": request,
            "product": product,
            "category": category,
            "parent_category": parent_category,
            "variant_options": variant_options,
        },
    )


@router.get("/partials/price/{product_id}")
async def get_product_price(product_id: str):
    # Check Ban Logic
    if should_ban(product_id, "products"):
        raise HTTPException(status_code=403, detail="Access Denied")

    product = data_manager.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # layout_no_price: prices are for signed-in members only, here too.
    if get_layout(product_id, "products") == "layout_no_price":
        raise HTTPException(status_code=401, detail="Sign in to see prices")

    return {
        "id": product.id,
        "price": product.price,
        "original_price": product.original_price,
        "currency": product.currency,
        "variants": [
            {"id": v.id, "price": v.price, "original_price": v.original_price}
            for v in product.variants
        ],
    }


# Hidden API Endpoints
def _get_breadcrumbs(category_id: str):
    breadcrumbs = []
    current_cat = data_manager.get_category(category_id)
    while current_cat:
        breadcrumbs.append({"id": current_cat.id, "name": current_cat.name})
        if current_cat.parent_id:
            current_cat = data_manager.get_category(current_cat.parent_id)
        else:
            current_cat = None
    return list(reversed(breadcrumbs))


@router.get("/data/category/{category_id}")
async def get_category_data(category_id: str):
    category = data_manager.get_category(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    response = category.model_dump()
    response["breadcrumbs"] = _get_breadcrumbs(category.id)
    response["layout"] = get_layout(category.id, "categories")
    response["ban"] = should_ban(category.id, "categories")

    products_list = []
    for p in data_manager.products.values():
        if p.category_id == category_id:
            p_data = p.model_dump()
            p_data["layout"] = get_layout(p.id, "products")
            p_data["ban"] = should_ban(p.id, "products")
            products_list.append(p_data)

    response["products"] = products_list
    response["product_count"] = len(products_list)
    return response


@router.get("/data/product/{product_id}")
async def get_product_data(product_id: str):
    product = data_manager.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    response = product.model_dump()
    response["breadcrumbs"] = _get_breadcrumbs(product.category_id)
    response["layout"] = get_layout(product.id, "products")
    response["ban"] = should_ban(product.id, "products")
    return response

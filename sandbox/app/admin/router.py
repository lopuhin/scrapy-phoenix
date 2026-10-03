import json
import os
import tempfile

from fastapi import APIRouter, Request, Form, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.core.config import settings, Settings, ENV_FILE
from app.core.data import data_manager

router = APIRouter()

# Setup templates
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def _serialize_settings_env(settings_obj: Settings) -> str:
    data = settings_obj.model_dump()
    data.pop("PROJECT_NAME", None)
    lines = []
    for key, value in data.items():
        if isinstance(value, str):
            value_str = json.dumps(value)
        else:
            value_str = str(value)
        lines.append(f"{key}={value_str}")
    return "\n".join(lines) + "\n"


def persist_settings_env(settings_obj: Settings, env_file: str = ENV_FILE) -> None:
    directory = os.path.dirname(env_file)
    if directory:
        os.makedirs(directory, exist_ok=True)
    content = _serialize_settings_env(settings_obj)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory or None, prefix=".settings.", text=True
    )
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(tmp_path, env_file)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def remove_settings_env(env_file: str = ENV_FILE) -> None:
    try:
        os.remove(env_file)
    except FileNotFoundError:
        pass


@router.get("/")
async def admin_dashboard(request: Request):
    # Exclude PROJECT_NAME and potentially other internal fields
    # We can iterate over all fields and exclude specific ones

    # Using model_dump() for Pydantic v2
    current_settings = settings.model_dump()
    default_settings = Settings(_env_file=None).model_dump()

    # Filter out PROJECT_NAME
    if "PROJECT_NAME" in current_settings:
        del current_settings["PROJECT_NAME"]
    if "PROJECT_NAME" in default_settings:
        del default_settings["PROJECT_NAME"]

    return templates.TemplateResponse(
        "admin/index.html",
        {
            "request": request,
            "settings": current_settings,
            "defaults": default_settings,
        },
    )


@router.post("/update")
async def update_settings(
    request: Request,
    ACTIVE_LAYOUT: str = Form(...),
    AB_TEST_RATIO: float = Form(...),
    AB_TEST_LAYOUT: str = Form(...),
    AB_TEST_TARGET: str = Form(...),
    AB_TEST_SEED: int = Form(...),
    BAN_RATIO: float = Form(...),
    BAN_STATUS_CODE: int = Form(...),
    BAN_TARGET: str = Form(...),
    BAN_SEED: int = Form(...),
    OUT_OF_STOCK_RATIO: float = Form(...),
    OUT_OF_STOCK_SEED: int = Form(...),
    DISCOUNT_RATIO: float = Form(...),
    DISCOUNT_SEED: int = Form(...),
    HAS_RATING_RATIO: float = Form(...),
    HAS_RATING_SEED: int = Form(...),
    PRODUCT_COUNT_SCALE: float = Form(...),
    DATA_GENERATION_SEED: int = Form(...),
    ITEMS_PER_PAGE: int = Form(...),
    BOOKS_COUNT_SCALE: float = Form(1.0),
    PRICE_SCALE: float = Form(1.0),
):
    # Update settings
    settings.ACTIVE_LAYOUT = ACTIVE_LAYOUT
    settings.AB_TEST_RATIO = AB_TEST_RATIO
    settings.AB_TEST_LAYOUT = AB_TEST_LAYOUT
    settings.AB_TEST_TARGET = AB_TEST_TARGET
    settings.AB_TEST_SEED = AB_TEST_SEED
    settings.BAN_RATIO = BAN_RATIO
    settings.BAN_STATUS_CODE = BAN_STATUS_CODE
    settings.BAN_TARGET = BAN_TARGET
    settings.BAN_SEED = BAN_SEED
    settings.OUT_OF_STOCK_RATIO = OUT_OF_STOCK_RATIO
    settings.OUT_OF_STOCK_SEED = OUT_OF_STOCK_SEED
    settings.DISCOUNT_RATIO = DISCOUNT_RATIO
    settings.DISCOUNT_SEED = DISCOUNT_SEED
    settings.HAS_RATING_RATIO = HAS_RATING_RATIO
    settings.HAS_RATING_SEED = HAS_RATING_SEED
    settings.PRODUCT_COUNT_SCALE = PRODUCT_COUNT_SCALE
    settings.BOOKS_COUNT_SCALE = BOOKS_COUNT_SCALE
    settings.PRICE_SCALE = PRICE_SCALE
    settings.DATA_GENERATION_SEED = DATA_GENERATION_SEED
    settings.ITEMS_PER_PAGE = ITEMS_PER_PAGE

    # Reload data manager
    data_manager.reload()
    try:
        persist_settings_env(settings)
    except OSError as exc:
        print(f"Warning: unable to persist settings to {ENV_FILE}: {exc}")

    return RedirectResponse(url="/admin/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/reset")
async def reset_settings(request: Request):
    # Create a fresh settings instance (env vars only; ignores persisted .env)
    default_settings = Settings(_env_file=None)

    # Update global settings with default values
    # We iterate and set attributes to ensure the global instance is updated in place
    for key, value in default_settings.model_dump().items():
        if hasattr(settings, key) and key != "PROJECT_NAME":
            setattr(settings, key, value)

    # Reload data manager
    data_manager.reload()
    try:
        remove_settings_env()
    except OSError as exc:
        print(f"Warning: unable to remove persisted settings {ENV_FILE}: {exc}")

    return RedirectResponse(url="/admin/", status_code=status.HTTP_303_SEE_OTHER)

import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.sites.sandbox_store.router import router as sandbox_router
from app.admin.router import router as admin_router
from app.core.config import settings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# No /openapi.json or /docs: they would list the ground-truth /data endpoints,
# which crawlers (and the repair agent) must not discover.
app = FastAPI(title=settings.PROJECT_NAME, openapi_url=None, docs_url=None, redoc_url=None)

app.mount(
    "/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static"
)

# Mount the Sandbox Store
app.include_router(sandbox_router, prefix="/sandbox-store", tags=["sandbox-store"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

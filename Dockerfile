# Scrapy Cloud image: the spiders, the healer and the agent's tools.
# Build and deploy with `shub image upload` (see deploy/README.md).
FROM python:3.13

ENV TERM=xterm \
    SCRAPY_SETTINGS_MODULE=sandbox_spider.settings \
    HOME=/tmp/home \
    PIP_NO_CACHE_DIR=1 \
    SELFHEAL_PERMISSION_MODE=bypassPermissions

WORKDIR /app
COPY pyproject.toml /app/
COPY . /app
RUN pip install -e '.[agent,test]' scrapinghub-entrypoint-scrapy scrapy-mcp-official

# Codex's own sandbox (bubblewrap/Landlock) can't start inside the container,
# so the agent's shell runs unsandboxed there: the container is the sandbox.
# The healer snapshots the project with git and adds modules to the live tree,
# and the job may run as another user: one commit, no history, writable.
RUN git config --system safe.directory '*' \
 && git init -q && git add -A \
 && git -c user.name=image -c user.email=image@localhost commit -qm snapshot \
 && mkdir -p "$HOME" && chmod -R a+rwX /app "$HOME"

# Scrapy Cloud

The project deploys as a custom image (`Dockerfile`): the spiders, the healer,
harness-run with the Codex CLI, scrapy-mcp and pytest. The image is a git repo
with one commit and no history, which is what the healer snapshots for the
agent.

Codex's own sandbox can't start inside the container, so the image sets
`SELFHEAL_PERMISSION_MODE=bypassPermissions`: the container is the sandbox.

## Deploy

    shub login                          # your Scrapy Cloud API key
    shub image upload <project id>      # builds with docker, pushes, deploys

## Run

The OpenAI key is a spider argument. It is visible in the job's metadata, so
use a temporary key with a spending limit and rotate it afterwards. The healer
passes it to Codex as a per-run secret and removes it from the spider object,
which the agent can inspect through scrapy-mcp.

    python scripts/drift.py product-modern --base <sandbox>
    shub schedule <project id>/sandbox_store \
        -a openai_api_key=sk-... \
        -s SELFHEAL_ENABLED=1 -s SANDBOX_URL=<sandbox>/sandbox-store/
    shub items <job key> > output/cloud-items.jsonl
    python scripts/score.py output/cloud-items.jsonl --base <sandbox>

Repair records (`repairs/`) live in the container and go with it; the job log
has the agent's events, the gate output and the outcome.

Tested: job 880721/4/5, Case A, 566/566 fully correct.

## Test the image locally first

    docker build -t scrapy-phoenix .
    docker run --rm --user 4321:4321 -w /tmp -v "$PWD/output/ct:/out" scrapy-phoenix \
        scrapy crawl sandbox_store -a openai_api_key="$OPENAI_API_KEY" \
        -O /out/items.jsonl -s SELFHEAL_ENABLED=1 -s SELFHEAL_REPAIRS_DIR=/out/repairs \
        -s SANDBOX_URL=<sandbox>/sandbox-store/

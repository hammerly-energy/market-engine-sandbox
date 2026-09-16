# The deploy image. Python solves and the browser draws, so the thing being
# shipped is a Python process with the editor mounted beside it -- not a static
# site. CLAUDE.md, "Why there is a server at all".
#
# Every host this branch targets builds this same file. Only the small config
# next to it differs, which is what keeps the choice of host reversible.

FROM python:3.11-slim

# HiGHS ships manylinux wheels, so there is no compiler step and no build-essential
# layer. If a future dependency needs one, add it here rather than reaching for
# a fatter base image.

WORKDIR /app

# Dependencies from pyproject.toml, which is the single source of truth. A
# hand-written requirements.txt listing only what the serve path imports would
# be smaller -- matplotlib and pyarrow are viz and parquet, and /clear touches
# neither -- and it would drift the first time pyproject changed and this did
# not. The repo is organised around not having two places for one fact.
#
# pandas and requests are not optional despite that: scenario.py imports
# eia930 at module scope, so they load even on the blocks path the editor uses.
COPY pyproject.toml LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY configs/ ./configs/
COPY web/ ./web/

# Run the tree at /app, not the copy pip put in site-packages, and say so
# rather than leaving it to sys.path ordering.
#
# app.py resolves the editor as Path(__file__).parents[2] / "web". From
# /app/src/api/app.py that is /app/web, which is the directory copied above.
# From site-packages/src/api/app.py it would be site-packages/web, which does
# not exist -- and the mount is guarded by `if WEB_DIR.is_dir()`, so the page
# would 404 while /clear kept answering. A silent half-deploy is worth one
# explicit line to prevent.
ENV PYTHONPATH=/app

# Render sets PORT and requires the server to bind 0.0.0.0; the CMD below does
# both. The default is only for running this image by hand, where nothing sets
# PORT -- on Render that branch is never taken.
ENV PORT=10000
EXPOSE 10000

# One worker, deliberately. The rate limiter counts in-process, so a second
# worker would let each allow the full rate (src/api/ratelimit.py). A solve on
# this five-bus case is milliseconds, so concurrency buys nothing here anyway.
CMD ["sh", "-c", "uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]

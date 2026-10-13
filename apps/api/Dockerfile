# Khazana Outlet API.
#
# Two targets:
#   dev     everything needed to develop: tests, ruff, mypy, alembic, seeding
#   runtime slim, non root, no dev tools, for deployment
#
# The ordering matters more than it looks. Dependencies are installed from
# pyproject.toml alone, before any source is copied, so editing a Python file
# does not invalidate the dependency layer. That is what makes the image build
# once and then start instantly, instead of downloading 70 MB on every run.

ARG PYTHON_VERSION=3.11.11

# ----------------------------------------------------------------- base
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    # A slow or unstable connection needs more than pip's 15 second default.
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# libpq is what psycopg needs to talk to PostgreSQL. curl is for the health
# check. Both are tiny and both are removed from the runtime image's build
# layer by the multi stage split.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*


# ----------------------------------------------------------- dependencies
FROM base AS deps

# A stub package so setuptools can resolve the project before the real source
# exists. The editable install writes a path entry pointing at /app/src, which
# the bind mount then fills with the actual code.
COPY pyproject.toml ./
RUN mkdir -p src/khazana \
    && touch src/khazana/__init__.py \
    && pip install -e ".[dev]"


# ------------------------------------------------------------------ dev
FROM deps AS dev

# Run as a normal user. Files created by the container land on the host with
# this ownership, and root owned files in a bind mounted folder are a nuisance
# to clean up afterwards.
RUN useradd --create-home --uid 1000 khazana \
    && chown -R khazana:khazana /app
USER khazana

ENV ENVIRONMENT=development \
    AI_OFFLINE=true \
    OTP_DEV_ECHO=true

# Overridden by compose for one off commands such as pytest or alembic.
CMD ["uvicorn", "khazana.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# -------------------------------------------------------------- runtime
FROM base AS runtime

# Only the runtime dependencies, no pytest, ruff or mypy.
COPY pyproject.toml ./
RUN mkdir -p src/khazana \
    && touch src/khazana/__init__.py \
    && pip install -e "." \
    && rm -rf /root/.cache

COPY --chown=1000:1000 . .

RUN useradd --create-home --uid 1000 khazana \
    && chown -R khazana:khazana /app
USER khazana

ENV ENVIRONMENT=production

EXPOSE 8000

# Liveness only. /health deliberately does not touch the database, so a brief
# database blip does not take the container out of rotation.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

CMD ["uvicorn", "khazana.main:app", "--host", "0.0.0.0", "--port", "8000"]

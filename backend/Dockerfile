# Pinned to 3.12: the LangChain/LangGraph dependency tree is not reliable on 3.14.
FROM python:3.12-slim

WORKDIR /srv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY app ./app
COPY tests ./tests

# The dev extra ships in the image on purpose: a reviewer who clones this repo
# can run `docker compose exec backend pytest` without a local Python setup.
RUN pip install --no-cache-dir ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

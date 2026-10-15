# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TATEMONO_CHROMIUM_EXECUTABLE=/usr/bin/chromium
COPY requirements.txt requirements-pdf.txt requirements-cloud.txt pyproject.toml ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir 'setuptools>=68' wheel -r requirements.txt -r requirements-cloud.txt && \
    apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY src ./src
RUN pip install --no-cache-dir --no-build-isolation --no-deps . && useradd --create-home collector && chown collector /app
USER collector
ENTRYPOINT ["python", "-m", "tatemono_map.cloud.run"]

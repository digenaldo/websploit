# mind-core: shared LLM backend for the WebSploit AI track.
# Shared infrastructure, NOT an intentionally vulnerable lab: pinned multi-arch
# base image (linux/amd64 + linux/arm64), hash-pinned dependencies, non-root.
FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MIND_CORE_BACKEND=deterministic

WORKDIR /app
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin mindcore

COPY app.py .
COPY backends/ backends/
COPY rules/ rules/

USER 10001
EXPOSE 5030
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5030/health', timeout=2).status == 200 else 1)"]
CMD ["python", "app.py"]

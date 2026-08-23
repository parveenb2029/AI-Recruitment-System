# Review console + pipeline, in one image.
#
#     docker compose up
#
# The image exists mainly to solve two problems the host cannot:
#
#   1. OCR needs Tesseract and Poppler, which are system binaries, not Python
#      wheels. Installing them on Windows is a manual download-and-PATH chore.
#      Here they are just apt packages, so scanned resumes work everywhere.
#   2. The Postgres driver, psycopg, is optional on the host precisely so a
#      laptop need not compile one. In the image there is no reason not to.

FROM python:3.12-slim

# PYTHONUNBUFFERED: the first-run password is printed to stdout, and a buffered
# stream would hide it behind uvicorn's startup noise for an alarming few seconds.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, in their own layer: they change far less often than the
# code, so editing a template does not reinstall the world.
COPY pyproject.toml ./
COPY src ./src
RUN pip install -e ".[postgres,ocr,anthropic,web]"

COPY . .

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Run as a non-root user. A document parser is exactly the kind of code that
# should not be root: it opens files it did not write, from people it has never
# met. `data` is created here so a named volume mounted over it stays writable.
RUN useradd --create-home --uid 10001 recruit \
    && mkdir -p /app/data \
    && chown -R recruit:recruit /app
USER recruit

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=40s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["console"]

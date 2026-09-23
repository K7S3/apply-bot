# syntax=docker/dockerfile:1
#
# candid — generic, local-first job-search copilot, one-command Docker run.
#
# Usage:
#   docker build -t candid .
#   docker run --rm -it -v candid-data:/data candid              # shows usage
#   docker run --rm -it -v candid-data:/data candid onboard       # interactive wizard
#   docker run --rm -p 8765:8765 -v candid-data:/data candid dashboard --host 0.0.0.0
#
# candid is stdlib-only; the only optional dependency is pypdf
# (needed for `onboard --resume file.pdf`).

# ---------------------------------------------------------------------------
# Builder: install the single optional dependency into an isolated target dir.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --target /opt/candid-deps -r requirements.txt

# ---------------------------------------------------------------------------
# Runtime: slim image, non-root user, app source, wizard-capable entrypoint.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Version for the OCI label; falls back to 0.2.0 if the source layout changes.
ARG CANDID_VERSION=0.2.0

LABEL org.opencontainers.image.title="candid" \
      org.opencontainers.image.description="Generic, local-first job-search copilot: onboarding, job matching, tailored resumes, application tracker, salary intelligence, interview prep, mock interviews, and a local dashboard." \
      org.opencontainers.image.source="https://github.com/K7S3/candid" \
      org.opencontainers.image.url="https://github.com/K7S3/candid" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${CANDID_VERSION}"

# Non-root user for everything at runtime.
RUN groupadd -r candid --gid 1000 && \
    useradd -r -m -u 1000 -g candid -s /bin/sh candid

# App source and the pre-installed optional dependencies.
COPY --chown=candid:candid . /app
COPY --from=builder --chown=candid:candid /opt/candid-deps /opt/candid-deps

# PYTHONPATH so `python -m candid` finds both the app and the deps.
ENV PYTHONPATH="/app:/opt/candid-deps" \
    CANDID_DATA_DIR=/data \
    CANDID_CONFIG_DIR=/home/candid/.config/candid \
    PATH="/home/candid/.local/bin:${PATH}"

WORKDIR /app

# Persisted user data (profile, tracker DB, tailor outputs).
VOLUME /data

# Dashboard port.
EXPOSE 8765

# Entrypoint prepares /data and offers the interactive onboarding wizard.
COPY --chown=candid:candid docker/entrypoint.sh /usr/local/bin/candid-entrypoint
RUN chmod 755 /usr/local/bin/candid-entrypoint

USER candid

ENTRYPOINT ["candid-entrypoint"]

# Bare `docker run` shows usage; pass a command like `onboard` or `dashboard`.
CMD ["--help"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import candid; print(candid.__version__)"

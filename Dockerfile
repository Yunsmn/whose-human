# One image for the logging server, certificate generation and the test suite.
# Only the server runs in Docker. Agents and scripts under test always run natively on the host.
FROM python:3.12.16-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY pyproject.toml ./
COPY infra/ infra/
COPY harness/ harness/
COPY model/ model/
COPY linking/ linking/

# Non-root user; uid 1000 matches the default first user on Linux hosts, so bind-mounted data/ stays writable.
RUN useradd --uid 1000 --create-home app && mkdir -p data && chown app:app data
USER app

EXPOSE 8443
ENTRYPOINT ["python", "-m", "infra.server"]
CMD ["--host", "0.0.0.0", "--port", "8443"]

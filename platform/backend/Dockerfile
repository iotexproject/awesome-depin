FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY platform/backend/requirements-model-runtime.txt /app/requirements-model.txt
COPY platform/backend/requirements.txt /app/requirements-api.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements-model.txt -r /app/requirements-api.txt

# Keep the production image's model payload explicit.  The repository also
# contains research exports and local datasets that are not runtime inputs and
# must not be swept into a customer-facing image.
COPY tools/qtail_data_engine.py /app/tools/qtail_data_engine.py
COPY tools/qtail_openx_service_model.py /app/tools/qtail_openx_service_model.py
COPY tools/qtail_build_package.py /app/tools/qtail_build_package.py
COPY tools/qtail_validate_package.py /app/tools/qtail_validate_package.py
COPY data/uploaded_data.csv /app/data/uploaded_data.csv
COPY results/openx_strong_training/openx_demo_training_report.json /app/results/openx_strong_training/openx_demo_training_report.json
COPY results/openx_strong_training/openx_shard_training_rows.csv /app/results/openx_strong_training/openx_shard_training_rows.csv
COPY platform/backend /app/platform/backend

RUN useradd --create-home --uid 10001 qtail \
    && mkdir -p /app/platform/var/jobs \
    && chown -R qtail:qtail /app/platform/var

USER qtail
EXPOSE 8787
CMD ["gunicorn", "--chdir", "/app/platform/backend", "--bind", "0.0.0.0:8787", "--workers", "2", "--threads", "4", "--timeout", "300", "app:app"]

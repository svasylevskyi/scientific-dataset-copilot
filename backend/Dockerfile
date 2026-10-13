FROM python:3.14.7-slim
ARG SDC_SOURCE_REVISION=unknown
ENV SDC_SOURCE_REVISION=$SDC_SOURCE_REVISION
WORKDIR /app
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY backend ./backend
RUN pip install --no-deps --no-build-isolation ./backend
RUN useradd --create-home app && mkdir -p /app/artifacts/runs && chown -R app:app /app/artifacts
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY cognitive_map ./cognitive_map
COPY providers ./providers
COPY router ./router
COPY runtime ./runtime
COPY sfe ./sfe
COPY sfe_proxy ./sfe_proxy

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e .

EXPOSE 17891

CMD ["python", "-m", "sfe_proxy"]

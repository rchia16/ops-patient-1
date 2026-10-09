FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY . .
RUN useradd --create-home --uid 10001 ops && chown -R ops:ops /app
USER ops

EXPOSE 10000
CMD ["python", "server/run.py"]

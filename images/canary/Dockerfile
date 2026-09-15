FROM python:3.12-slim

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin canary

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY canary.py .

USER canary
EXPOSE 9101
ENTRYPOINT ["python", "-u", "/app/canary.py"]

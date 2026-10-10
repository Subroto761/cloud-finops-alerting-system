FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY finops ./finops

RUN useradd --system --create-home --home-dir /home/finops finops
USER finops

EXPOSE 9108
CMD ["python", "-m", "finops", "exporter"]

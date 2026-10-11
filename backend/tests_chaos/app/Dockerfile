FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY service.py .
# PYTHONUNBUFFERED so log lines reach the shipper immediately rather than
# sitting in a block buffer — a batch that arrives late lands outside the
# analysis window and looks like missing data.
ENV PYTHONUNBUFFERED=1
CMD ["python", "service.py"]

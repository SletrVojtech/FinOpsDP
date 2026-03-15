FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app

# Default, can be overwritten in Docker compose
CMD ["python3", "data_collector/run_policies.py", "loader"]
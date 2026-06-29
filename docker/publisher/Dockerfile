FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY contracts/abis/ /contracts/abis/
COPY analytics-engine/strategies/ /app/analytics-engine/strategies/
ENV PYTHONPATH=/app
CMD ["python", "-m", "archimedes.chain.strategy_runner_publisher"]

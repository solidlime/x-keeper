FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV SAVE_PATH=/data

EXPOSE 8989

CMD ["python", "-m", "src.main"]

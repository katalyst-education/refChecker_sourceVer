FROM python:3.11-slim

WORKDIR /app

COPY Extraction-Serv/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY Extraction-Serv/service_core /app/service_core
COPY Extraction-Serv/app /app/app
COPY Extraction-Serv/tests /app/tests
COPY Extraction-Serv/README.md /app/README.md

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]



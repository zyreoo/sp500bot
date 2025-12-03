
FROM python:3.11-slim


WORKDIR /app


RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*


COPY requirements.txt .


RUN pip install --no-cache-dir -r requirements.txt


COPY __init__.py .


EXPOSE 5001


ENV FLASK_APP=__init__.py
ENV PYTHONUNBUFFERED=1

CMD ["python", "__init__.py", "--web"]



FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy


WORKDIR /app


ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1


COPY requirements.txt .
RUN pip install --upgrade pip
RUN apt-get update && apt-get install -y tzdata
RUN pip install --no-cache-dir -r requirements.txt


RUN python -m playwright install chromium


COPY . .


EXPOSE 8000


CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "urbix.asgi:application"]
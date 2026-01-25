# Use Python 3.11 (Slim version is faster/smaller)
FROM python:3.11-slim

# Prevent Python from writing temporary files to disk
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Create a folder inside the container
WORKDIR /app

# Install system tools needed for some Python packages
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy your requirements and install them
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy your entire project code into the container
COPY . /app/
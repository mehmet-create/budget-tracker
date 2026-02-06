# Use Python 3.11
FROM python:3.11-slim

# Keep Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies
# Added 'dos2unix' to fix Windows line-ending issues in scripts
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# --- CRITICAL FIXES FOR DEPLOYMENT ---

# 1. Fix line endings (If you created run.sh on Windows, this prevents a crash)
RUN dos2unix run.sh

# 2. Make the script executable
RUN chmod +x run.sh

# 3. The Command: Execute your startup script
CMD ["./run.sh"]
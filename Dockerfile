# File: Dockerfile

# Use an official Python runtime as a parent image
# Choose a version compatible with discord.py and your other dependencies (e.g., 3.10 or 3.11)
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1  # Prevents python from writing .pyc files
ENV PYTHONUNBUFFERED 1      # Prevents python from buffering stdout and stderr

# Set the working directory in the container
WORKDIR /app

# Install system dependencies that might be needed by Python packages (if any)
# For discord.py, sometimes voice support or certain image libraries need them.
# Basic setup usually doesn't need much beyond what python-slim provides.
# RUN apt-get update && apt-get install -y --no-install-recommends some-package && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
# Using --no-cache-dir can reduce image size slightly
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Ensure the data and logs directories exist and have appropriate permissions if needed
# (Python will create them if the user has permission, but good to be explicit for non-root users later)
RUN mkdir -p /app/data && mkdir -p /app/logs
# If running as non-root, you'd chown these here. For now, default root execution is simpler.

# Command to run the application
CMD ["python", "main.py"]
# Use a lightweight Python image
FROM python:3.11-alpine

# Set the working directory in the container
WORKDIR /app

# Install build dependencies for xxhash and other Python packages
# build-base includes gcc, python3-dev, etc., needed for compiling some Python packages.
RUN apk add --no-cache build-base

# Install Python dependencies required by the server.
RUN pip install --no-cache-dir peewee fastapi uvicorn xxhash requests python-multipart

# Copy only the necessary files for the server
# These files are required for the FastAPI server to run.
COPY server.py ./
COPY database.py ./
COPY config.py ./
COPY assets.py ./
COPY file_info.py ./

# Create a settings.toml specifically for the server container.
# This defines the logical base_path for the server's database records
# and the data_path where actual file content will be stored (mounted volume).
RUN echo '[core]' > settings.toml && \
    echo 'base_path = "/sync_root"' >> settings.toml && \
    echo 'data_path = "/app/data"' >> settings.toml && \
    echo 'server_hostname = "0.0.0.0"' >> settings.toml && \
    echo 'server_port = 8000' >> settings.toml

# Expose the port the FastAPI application will run on
EXPOSE 8000

# Command to run the FastAPI application using uvicorn.
# The server:app refers to the 'app' object in 'server.py'.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
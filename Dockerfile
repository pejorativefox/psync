FROM python:3.11-alpine

# Set the working directory in the container
WORKDIR /app

# Install build dependencies
RUN apk add --no-cache build-base

# Install Python dependencies required by the server.
RUN pip install --no-cache-dir peewee fastapi uvicorn xxhash requests python-multipart platformdirs

# Copy only the necessary files for the server
# These files are required for the FastAPI server to run.
COPY server.py ./
COPY database.py ./
COPY config.py ./
COPY file_info.py ./
COPY sync.py ./
COPY watch.py ./

# Expose the port the FastAPI application will run on
EXPOSE 8000

# Command to run the FastAPI application using uvicorn.
# The server:app refers to the 'app' object in 'server.py'.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]

# Use official lightweight Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy files
COPY . .

# Install dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Expose port for Render
EXPOSE 10000

# Run the app
CMD ["uvicorn", "memory_server:app", "--host", "0.0.0.0", "--port", "10000"]

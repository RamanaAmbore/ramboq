FROM python:3.13-slim

WORKDIR /app

# Install dependencies as a separate layer for cache reuse
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Remove any accidentally included secrets (defence in depth)
RUN rm -f setup/yaml/secrets.yaml setup/yaml/ramboq_deploy.yaml

EXPOSE 8504

CMD ["streamlit", "run", "app.py", \
     "--server.port=8504", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]

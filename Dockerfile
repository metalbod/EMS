FROM python:3.11-slim

WORKDIR /app

# Keep Python from buffering stdout/stderr so `fly logs` shows output immediately
ENV PYTHONUNBUFFERED=1

# Baked in by deploy.sh (--build-arg) from the git commit being deployed —
# the image has no .git of its own (see .dockerignore), so this is the
# only way routers/frontend.py's login-screen version label can know what
# it's actually running. Defaults to "dev" for a manual `docker build`
# with no build-arg passed.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim

WORKDIR /app

# Keep Python from buffering stdout/stderr so `fly logs` shows output immediately
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baked in by deploy.sh (--build-arg) from the git commit being deployed —
# the image has no .git of its own (see .dockerignore), so this is the
# only way routers/frontend.py's login-screen version label can know what
# it's actually running. Defaults to "dev" for a manual `docker build`
# with no build-arg passed. Placed after the pip install (not before it,
# where an ARG/ENV would sit more naturally) deliberately — APP_VERSION
# changes on every single deploy, and an ARG changing invalidates every
# layer after it, which would otherwise force a full dependency reinstall
# on every deploy instead of hitting Docker's build cache. COPY . . below
# already changes every deploy anyway, so losing cache from this point on
# costs nothing extra.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

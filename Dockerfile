# Resume Matcher Docker Image
# Multi-stage build for optimized image size

# ============================================
# Stage 1: Build Frontend
# ============================================
FROM node:22-bookworm AS frontend-builder

# Build argument for API URL (allows customization at build time)
# Default routes requests through Next.js rewrites on the same origin.
ARG NEXT_PUBLIC_API_URL=/
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

WORKDIR /app/frontend

# Copy package files first for better caching
COPY apps/frontend/package*.json ./

# Install dependencies
RUN npm ci

# Copy frontend source
COPY apps/frontend/ ./

# Build the frontend
RUN npm run build

# ============================================
# Stage 2: Final Image
# ============================================
FROM python:3.13-slim-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    # Playwright dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    # CJK fonts for Chinese/Japanese/Korean PDF rendering via Playwright
    fonts-noto-cjk \
    # Latin resume fonts: without these, headless Chromium in a slim base falls
    # back to Noto Sans SC (Chinese) for Latin glyphs — ATS-hostile, visually off.
    # Metric-compatible substitutes (liberation2 = Arial/Times/Courier;
    # carlito = Calibri; caladea = Cambria) keep the standard CSS font stacks
    # honest without the proprietary faces, plus popular resume choices.
    fonts-liberation2 \
    fonts-dejavu \
    fonts-inter \
    fonts-roboto \
    fonts-lato \
    fonts-open-sans \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-firacode \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Node.js runtime from the frontend builder. Also copy npm/npx and the
# corepack directory so the dev-mode overlay (docker-compose.dev.yml) can run
# `next dev` inside this same image without a separate dev Dockerfile. The
# production runtime uses only `node server.js`, so the extra binaries are
# unused there — they're just kept present to make dev mode drop-in.
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
# npm/npx are wrapper scripts installed alongside node in the node:22 image;
# symlink them so PATH still resolves them.
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# ============================================
# Backend Setup
# ============================================
COPY apps/backend/pyproject.toml /app/backend/
COPY apps/backend/app /app/backend/app

WORKDIR /app/backend

# Install Python dependencies
RUN pip install .

# ============================================
# Frontend Setup
# ============================================
WORKDIR /app/frontend

# Copy standalone frontend runtime from builder stage
COPY --from=frontend-builder /app/frontend/.next/standalone ./
COPY --from=frontend-builder /app/frontend/.next/static ./.next/static
COPY --from=frontend-builder /app/frontend/public ./public
# Also copy the full node_modules and package.json from the builder. The
# production start.sh doesn't need these (it runs `node server.js` from the
# standalone bundle which has its own deps), so this only costs image size
# for dev-mode convenience. When docker-compose.dev.yml mounts the host's
# ./apps/frontend over this directory, the anonymous volume on
# /app/frontend/node_modules seeds from THIS copy — giving the container a
# proper linux-arm64 node_modules independent of the host's darwin-arm64 one.
COPY --from=frontend-builder /app/frontend/node_modules ./node_modules
COPY --from=frontend-builder /app/frontend/package.json ./package.json

# ============================================
# Startup Script
# ============================================
COPY docker/start.sh /app/start.sh
# Convert CRLF to LF (fixes Windows line ending issues) and make executable
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

# ============================================
# Data Directory & Volume
# ============================================
RUN mkdir -p /app/backend/data

# Create a non-root user for security
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

# Install Playwright Chromium as appuser (so browsers are in correct location)
RUN python -m playwright install chromium

# Expose the public port (backend remains internal on 8000)
EXPOSE 3000

# Volume for persistent data
VOLUME ["/app/backend/data"]

# Set working directory
WORKDIR /app

# Health check on internal backend port only (independent of host port mapping).
HEALTHCHECK --interval=10s --timeout=10s --start-period=30s --retries=5 \
    CMD curl -f http://127.0.0.1:8000/api/v1/health || exit 1

# Start the application
CMD ["/app/start.sh"]

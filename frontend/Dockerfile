# Stage 1: Build the application
FROM node:22.12.0-alpine AS builder

# API base URL baked into the JS bundle at build time (Vite requirement —
# import.meta.env values are compile-time constants). Default is the
# same-origin relative path ``/api`` which works for every stock
# deployment where a reverse proxy (Caddy in the docker-compose
# quick-start, ingress in Helm) fronts both frontend + backend on the
# same host. Prior default was ``http://localhost:8000/api`` — a leftover
# from local dev that produced non-functional public images (Batch 45).
#
# Override for exotic topologies where the API lives on a different
# host, e.g. api.example.com serving app.example.com:
#     docker build --build-arg VITE_BASE_URL=https://api.example.com/api .
ARG VITE_BASE_URL=/api

WORKDIR /serops-front

# Copy package files and install ALL dependencies (including devDependencies for Vite)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code
COPY . .

# Create .env file with the build argument
RUN echo "VITE_BASE_URL=${VITE_BASE_URL}" > .env

# Build the application
# --max-old-space-size=1536 keeps Node heap within CI runner memory limits
RUN NODE_OPTIONS="--max-old-space-size=1536" npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

# Copy built assets from builder stage
COPY --from=builder /serops-front/dist /usr/share/nginx/html

# Copy nginx configuration for SPA routing
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]

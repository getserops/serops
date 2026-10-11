# Stage 1: Build the documentation
FROM python:3.12-alpine AS builder

WORKDIR /docs

# Install MkDocs and dependencies
RUN pip install --no-cache-dir \
    mkdocs-material \
    pymdown-extensions

# Copy documentation source
COPY . .

# Build static site.
#
# --strict so a broken link fails the image build rather than shipping. CI
# checks the same thing on pull requests; this is the backstop for anything
# that reaches main another way.
RUN mkdocs build --strict

# Stage 2: Serve with nginx
FROM nginx:alpine

# Copy built site from builder
COPY --from=builder /docs/site /usr/share/nginx/html

# Copy nginx configuration for static-site routing
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

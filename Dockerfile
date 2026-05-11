# ========================================
# Stage 1: Build Dashboard
# ========================================
FROM node:20-alpine AS builder

WORKDIR /app

# Copy workspace config
COPY package.json package-lock.json ./
COPY packages/shared/package.json packages/shared/
COPY packages/dashboard/package.json packages/dashboard/

# Install dependencies
RUN npm ci --workspace=packages/shared --workspace=packages/dashboard --include-workspace-root

# Copy source
COPY tsconfig.json ./
COPY packages/shared/ packages/shared/
COPY packages/dashboard/ packages/dashboard/

# Build dashboard
RUN npm -w packages/dashboard run build

# ========================================
# Stage 2: Serve with Nginx + Proxy
# ========================================
FROM nginx:alpine

# Built assets
COPY --from=builder /app/packages/dashboard/dist /usr/share/nginx/html

# Nginx config — SPA routing + backend proxy
COPY packages/dashboard/nginx.docker.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

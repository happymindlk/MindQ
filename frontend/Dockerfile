# --- Build: static production bundle (not the Vite dev server) ---------------
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
# Reproducible install from the lockfile (matches CI).
RUN npm ci --legacy-peer-deps

COPY . .

# Vite inlines these at build time; pass with --build-arg.
ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_FRONTEND_URL
ARG VITE_APP_VERSION
ENV VITE_API_URL=$VITE_API_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_FRONTEND_URL=$VITE_FRONTEND_URL \
    VITE_APP_VERSION=$VITE_APP_VERSION
RUN npm run build

# --- Serve: nginx with SPA fallback -------------------------------------------
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]

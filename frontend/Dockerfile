# Stage 1: Build static assets
FROM node:22-alpine AS builder

WORKDIR /app

# Use npm with mirror for stable non-interactive Docker builds
RUN npm config set registry https://registry.npmmirror.com

COPY package.json ./
RUN npm install

COPY . ./
RUN npm run build

# Stage 2: Nginx server with reverse proxy
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

# Build stage
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

# Serve stage
FROM nginx:stable-alpine
RUN apk add --no-cache gettext
COPY nginx.conf /etc/nginx/conf.d/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD envsubst '${API_UPSTREAM}' < /etc/nginx/conf.d/default.conf.template \
    > /etc/nginx/conf.d/default.conf && \
    nginx -g 'daemon off;'

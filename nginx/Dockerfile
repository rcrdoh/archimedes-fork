FROM node:22 AS ui-build
WORKDIR /app
COPY ui/package.json ui/package-lock.json ./
RUN npm install --prefer-offline
COPY ui/ .
RUN npm run build

FROM nginx:alpine
COPY --from=ui-build /app/dist /usr/share/nginx/html
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

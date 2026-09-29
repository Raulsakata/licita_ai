FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package*.json ./
COPY apps/api/package.json apps/api/package.json
COPY apps/web/package.json apps/web/package.json
RUN npm install --omit=dev

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=dependencies /app/node_modules ./node_modules
COPY package.json ./package.json
COPY apps/api ./apps/api
EXPOSE 3000
CMD ["node", "apps/api/src/server.js"]

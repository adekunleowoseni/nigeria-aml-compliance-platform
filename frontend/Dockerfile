FROM node:20-bookworm-slim AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --include=optional

FROM node:20-bookworm-slim AS dev
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["npm","run","dev"]


FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# Dev server for local-first usage; swap to `npm run build && npm run preview`
# for a production static bundle.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
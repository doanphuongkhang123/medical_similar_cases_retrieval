FROM node:22.23.0-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY src ./src
COPY test ./test
COPY verification ./verification

EXPOSE 4000
CMD ["npm", "start"]

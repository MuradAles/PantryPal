# The Vite dev server is what compose runs: this is a take-home, and a dev server
# with HMR is more useful to a reviewer than an nginx-served production bundle.
FROM node:22-alpine

WORKDIR /srv

# The lockfile is copied and `npm ci` used so a clone builds the same tree we
# verified, rather than whatever npm resolves on the day.
COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.js tailwind.config.js postcss.config.js ./
COPY src ./src

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

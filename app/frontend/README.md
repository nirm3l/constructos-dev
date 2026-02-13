# Frontend

Stack:
- React
- TypeScript
- TanStack Query
- Vite

## Local development

```bash
cd app/frontend
npm install
npm run dev
```

Vite proxies `/api` to `http://localhost:8000`.

## Production build

```bash
cd app/frontend
npm install
npm run build
```

Build output goes to `dist/` and is copied to `app/static/` in Docker image build.

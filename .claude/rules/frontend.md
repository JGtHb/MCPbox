---
paths:
  - "frontend/**"
---
# Frontend Rules

- React 18 + TypeScript strict mode
- Functional components only, no class components
- Use TanStack Query for all data fetching (not raw fetch/axios)
- Use React Router for navigation
- Tailwind CSS for styling — no CSS modules or styled-components
- Shared constants in `src/lib/constants.ts` (METHOD_COLORS, STATUS_COLORS, etc.)
- API client functions in `src/api/` (one file per domain)
- Custom hooks in `src/hooks/` (e.g., `useCopyToClipboard`)
- Page components in `src/pages/`, reusable UI in `src/components/`
- Routes defined in `src/routes.tsx`
- `VITE_API_URL` environment variable for backend URL (set at build time)
- ESLint + Prettier enforced

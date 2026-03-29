# Stock Game Frontend

React 18 + TypeScript + Vite + Ant Design frontend for the stock-game project.

## Setup

1. Install dependencies:

   npm install

2. Create local environment file from template:

   copy .env.example .env.local

3. Fill Supabase values in .env.local:

   VITE_SUPABASE_URL
   VITE_SUPABASE_ANON_KEY

4. Start development server:

   npm run dev

## Auth Notes (P8)

- Auth is powered by Supabase JS SDK.
- Session token is managed by Supabase and read from browser storage.
- API requests auto-attach Bearer token when a session exists.
- Do not put any secret key in frontend env files.

## Commands

- npm run dev
- npm run build
- npm run lint

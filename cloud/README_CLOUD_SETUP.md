# Job Agent Cloud Infrastructure — setup required (not live yet)

This directory contains an **optional** Supabase/Google-auth starter and private database schema. It is **not enabled by installing the local patch**. The existing Vercel website remains a Demo until all account and security prerequisites are completed.

## Capabilities represented here

- Google account sign-in through Supabase Auth; this is **NOT Gmail message access**.
- Private profile/job/application/resume tables with user-owned Postgres RLS.
- Private DOCX storage bucket with per-user path isolation.
- Read-only, authenticated Next.js jobs API example.
- Agent run records and optional schedule schema.
- Restricted Gmail credential table inaccessible to client roles.

## User-owned setup still required

1. Create a private Supabase project and review/apply `schema.sql` using its SQL Editor. Use a test project first.
2. In Google Cloud Console, configure an OAuth consent screen and **Google sign-in only**; configure its redirect URI to the Supabase callback URL supplied in Supabase Auth settings. Configure allowed domains in Supabase.
3. In Vercel set `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable key only). **Never** put a service-role or Gmail refresh token in `NEXT_PUBLIC_*` vars.
4. At your own pace, install `npm install @supabase/supabase-js @supabase/ssr` inside `frontend`; review and merge `cloud/nextjs/src/` into `frontend/src/`, and make an authenticated workspace before deploying private data.
5. Set up **separate Gmail OAuth** to request `gmail.readonly` only after explicit authorization. This scope is restricted and may require Google verification and security assessment for public apps. Store refresh tokens encrypted in a backend-only service; implement disconnect/revoke.
6. Provision and deploy a persistent, authenticated **worker** for Gmail/Playwright and a queue claiming protocol. Current local `api_local.py` CANNOT be deployed publicly; it is loopback-only and has no multi-user authentication.
7. Test authorization across two accounts, RLS, signed private file downloads, task authorization, logging redaction, and a complete user-initiated resume generation before switching the web UI away from Demo.

## Security gates

- Cloud auth is intentionally not silently enabled by copying this package.
- Never upload `APIkey.env`, `token.json`, `credentials.json`, `profile_data.json`, `application_tracker.json`, `jobs/`, `resumes/`, browser sessions or private DOCX templates to GitHub.
- Service role credentials must never be present in browser bundles or Git repository. Limit Google scopes and do not forward Gmail tokens to the Next.js client.
- Do not run `cloud/schema.sql` against a production database without reviewing permissions and migrations, including possibly existing storage policies.

## What is not yet implemented

A production Gmail consent/callback, encrypted OAuth token rotation, cloud worker, real time progress sync, Google verification process, billing/quotas, cloud private DOCX signing, and a complete cloud resume generation pathway. Those depend on owner-provided accounts and security configurations and must be tested before claiming readiness.

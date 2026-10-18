import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

// True only when both env vars are present. When false the app still mounts
// (so we can show a clear message instead of a blank white screen).
export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey);

if (!isSupabaseConfigured) {
  console.warn(
    'Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY. Set them in frontend/.env.local ' +
      'and RESTART the dev server (Vite only reads env vars at startup).'
  );
} else if (
  typeof supabaseUrl === 'string' &&
  supabaseUrl.includes('djshmrkerssvpcxqkqo') &&
  !supabaseUrl.includes('djshmrkerssvpvcxqkqo')
) {
  // Known Cloudflare Pages typo: missing "v" in the project ref → DNS NXDOMAIN.
  console.error(
    '[supabase] VITE_SUPABASE_URL looks like a typo (…svpc… instead of …svpvc…). ' +
      'Expected https://djshmrkerssvpvcxqkqo.supabase.co — update Cloudflare Pages env and redeploy.'
  );
}

// Use harmless placeholders when unconfigured so createClient does not throw at
// import time (an import-time throw crashes the whole app -> blank page).
export const supabase = createClient(
  supabaseUrl || 'http://localhost:54321',
  supabaseAnonKey || 'anon-key-not-configured',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  }
);

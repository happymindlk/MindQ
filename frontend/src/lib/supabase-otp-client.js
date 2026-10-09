import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

// Separate, non-persisting client so HR OTP verification never writes the ops
// portal's Supabase session. Its token lives only long enough to be exchanged
// for a backend-minted client JWT.
export const supabaseOtp = createClient(
  supabaseUrl || 'http://localhost:54321',
  supabaseAnonKey || 'anon-key-not-configured',
  {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
      storageKey: 'assesspulse-client-otp',
    },
  },
);

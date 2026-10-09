import React, { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { Mail, Lock, ArrowRight, Package } from 'lucide-react';
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';
import Button from '../../components/ui/Button';
import { useAuth } from '../../context/useAuth';
import { isOpsRole, resolveRole } from '../../lib/auth-role';
import { isSupabaseConfigured, supabase } from '../../lib/supabaseClient';

export default function AdminLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const { signIn, refreshMembership } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const from = location.state?.from?.pathname || '/admin/history';

  const handleLogin = async (e) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      const { error: signInError } = await signIn(email, password);
      if (signInError) throw signInError;
      const membership = await refreshMembership();
      if (!membership?.corporateId) {
        navigate('/pending-approval', { replace: true });
        return;
      }
      const { data } = await supabase.auth.getSession();
      const role = membership.role || resolveRole(data.session, null);
      if (!isOpsRole(role)) {
        navigate('/client/dashboard', { replace: true });
        return;
      }
      navigate(from.startsWith('/admin') ? from : '/admin/history', { replace: true });
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex flex-col justify-center items-center p-4">
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-2 text-primary-text mb-8">
          <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
            <Package className="w-5 h-5" />
          </div>
          <span className="font-semibold text-xl text-foreground">MindQ</span>
        </div>

        <Card variant="elevated" className="p-8">
          <h1 className="text-xl font-semibold text-foreground mb-1">Admin Portal</h1>
          <p className="text-neutral-400 text-sm mb-6">
            Enter your credentials to access the administrative console.
          </p>

          {!isSupabaseConfigured && (
            <div className="text-sm text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 mb-5">
              Supabase is not configured. Set <code>VITE_SUPABASE_URL</code> and{' '}
              <code>VITE_SUPABASE_ANON_KEY</code> in <code>frontend/.env.local</code> and restart the dev server.
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-5">
            <Input
              label="Email"
              type="email"
              icon={Mail}
              placeholder="ops@mindq.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <Input
              label="Password"
              type="password"
              icon={Lock}
              placeholder="Your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />

            {error && (
              <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" size="lg" isLoading={isLoading} disabled={!email || !password}>
              Sign In
              {!isLoading && <ArrowRight className="w-5 h-5 ml-2" />}
            </Button>
          </form>
        </Card>

        <p className="mt-6 text-center text-sm text-neutral-400">
          Looking for candidate or client access?{' '}
          <Link
            to="/portal"
            className="text-foreground underline-offset-4 hover:underline focus:outline-none focus-visible:underline focus-visible:text-primary-text"
          >
            Candidate access
          </Link>
          <span aria-hidden className="mx-2 text-neutral-600">·</span>
          <Link
            to="/client/login"
            className="text-foreground underline-offset-4 hover:underline focus:outline-none focus-visible:underline focus-visible:text-primary-text"
          >
            Client access
          </Link>
        </p>
      </div>
    </div>
  );
}

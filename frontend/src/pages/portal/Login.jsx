import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { KeyRound, Mail, User, ArrowRight } from 'lucide-react';
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';
import Button from '../../components/ui/Button';
import { api } from '../../api/client';

export default function Login() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [accessCode, setAccessCode] = useState('');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const code = searchParams.get('code');
    if (code) {
      setAccessCode(code.toUpperCase().trim());
    }
  }, [searchParams]);

  const handleLogin = async (e) => {
    e.preventDefault();
    if (!accessCode || !email || !fullName.trim()) return;
    setIsLoading(true);
    try {
      const res = await api.candidate.login({
        access_code: accessCode,
        email,
        full_name: fullName.trim(),
      });
      localStorage.setItem('candidateToken', res.token);
      localStorage.setItem('candidateName', res.full_name);
      localStorage.setItem('candidateId', res.id);
      navigate('/portal/guidelines');
    } catch (err) {
      console.error(err);
      alert('Login failed: ' + err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col justify-center items-center w-full min-h-[calc(100vh-12rem)]">
      <div className="w-full max-w-md">
        <div className="text-center mb-10">
          <h1 className="text-3xl font-bold text-slate-50 mb-3">Welcome to your Assessment</h1>
          <p className="text-slate-400">
            Enter your access code and identity. Full name is required so HR can match you even if you use a personal email.
          </p>
        </div>

        <Card variant="elevated" className="p-8">
          <form onSubmit={handleLogin} className="space-y-6">
            <Input
              label="Access Code"
              icon={KeyRound}
              placeholder="e.g. HM-ABCDEF-1"
              value={accessCode}
              onChange={(e) => setAccessCode(e.target.value.toUpperCase())}
              required
            />
            <Input
              label="Full Name"
              icon={User}
              placeholder="Name as HR should see it on reports"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
            />
            <Input
              label="Email Address"
              type="email"
              icon={Mail}
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <Button
              type="submit"
              className="w-full mt-8"
              size="lg"
              isLoading={isLoading}
              disabled={!accessCode || !email || !fullName.trim()}
            >
              Continue
              {!isLoading && <ArrowRight className="w-5 h-5 ml-2" />}
            </Button>
          </form>
        </Card>
        <p className="text-center text-sm text-slate-500 mt-8">
          Technical issues? Use the support button without leaving this page.
        </p>
      </div>
    </div>
  );
}

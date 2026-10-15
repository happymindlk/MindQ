import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useSearchParams } from 'react-router-dom';

import { AuthProvider } from './context/AuthContext.jsx';
import { useAuth } from './context/useAuth';
import ProtectedRoute from './components/ProtectedRoute';

import Layout from './components/Layout';
import ClientLayout from './components/ClientLayout';
import PortalLayout from './components/PortalLayout';

import AdminLogin from './pages/admin/Login';
import Dashboard from './pages/admin/Dashboard';
import Corporates from './pages/admin/Corporates';
import CorporateDetail from './pages/admin/corporates/corporate-detail';
import AssessmentLibrary from './pages/admin/AssessmentLibrary';
import SuiteBuilder from './pages/admin/SuiteBuilder';
import AssessmentHistory from './pages/admin/AssessmentHistory';
import CandidateReport from './pages/admin/CandidateReport';
import AccountSettings from './pages/admin/AccountSettings';
import PendingApproval from './pages/PendingApproval';

import ClientLogin from './pages/client/login';
import ClientReview from './pages/client/Review';
import ClientDashboard from './pages/client/dashboard';
import ClientCandidateReport from './pages/client/candidate-report';
import ClientRoute from './pages/client/client-route';
import ClientSessionProvider from './pages/client/client-session-provider';

import Login from './pages/portal/Login';
import Guidelines from './pages/portal/Guidelines';
import TestDashboard from './pages/portal/TestDashboard';
import TestRunner from './pages/portal/TestRunner';
import PublicTrack from './pages/public/PublicTrack';

function AssessmentRedirect() {
  const [params] = useSearchParams();
  const code = params.get('code');
  const search = code ? `?code=${encodeURIComponent(code)}` : '';
  return <Navigate to={`/portal${search}`} replace />;
}

/**
 * `/` is the product entry, not a client bounce.
 * Unauthenticated → /admin/login. Ops/admin → /admin/history. HR → /client/*.
 */
function RootRedirect() {
  const { session, corporateId, loading, isOps } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas text-muted">
        Loading...
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/admin/login" replace />;
  }

  if (!corporateId) {
    return <Navigate to="/pending-approval" replace />;
  }

  if (isOps) {
    return <Navigate to="/admin/history" replace />;
  }

  return <Navigate to="/client/dashboard" replace />;
}

function App() {
  return (
    <AuthProvider>
      <ClientSessionProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<RootRedirect />} />

          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/client/login" element={<ClientLogin />} />
          <Route path="/pending-approval" element={<PendingApproval />} />
          <Route path="/public/track/:secret" element={<PublicTrack />} />
          <Route path="/client/review/:packageToken" element={<ClientReview />} />

          <Route
            path="/admin"
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="corporates" element={<Corporates />} />
            <Route path="corporates/:corporateId" element={<CorporateDetail />} />
            <Route path="library" element={<AssessmentLibrary />} />
            <Route path="packages/create" element={<SuiteBuilder />} />
            <Route path="packages/edit/:packageId" element={<SuiteBuilder />} />
            <Route path="packages/:packageId" element={<SuiteBuilder />} />
            <Route path="history" element={<AssessmentHistory />} />
            <Route path="history/:companyId" element={<AssessmentHistory />} />
            <Route path="history/:companyId/:packageId" element={<AssessmentHistory />} />
            <Route path="track" element={<Navigate to="/admin/history" replace />} />
            <Route path="candidates/:candidateId" element={<CandidateReport />} />
            <Route path="candidates" element={<Navigate to="/admin/history" replace />} />
            <Route path="settings" element={<AccountSettings />} />
          </Route>

          <Route path="/track/:packageId" element={<Navigate to="/admin/history" replace />} />

          <Route
            path="/client"
            element={
              <ClientRoute>
                <ClientLayout />
              </ClientRoute>
            }
          >
            <Route index element={<Navigate to="/client/dashboard" replace />} />
            <Route path="dashboard" element={<ClientDashboard />} />
            <Route path="candidates/:candidateId" element={<ClientCandidateReport />} />
          </Route>

          <Route path="/assessment" element={<AssessmentRedirect />} />

          <Route path="/portal" element={<PortalLayout />}>
            <Route index element={<Login />} />
            <Route path="guidelines" element={<Guidelines />} />
            <Route path="dashboard" element={<TestDashboard />} />
            <Route path="test/:testId" element={<TestRunner />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </ClientSessionProvider>
    </AuthProvider>
  );
}

export default App;

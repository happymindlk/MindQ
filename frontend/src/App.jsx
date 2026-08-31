import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { AuthProvider } from './context/AuthContext.jsx';
import ProtectedRoute from './components/ProtectedRoute';

// Layouts
import Layout from './components/Layout';
import PortalLayout from './components/PortalLayout';

// Admin Pages
import AdminLogin from './pages/admin/Login';
import Dashboard from './pages/admin/Dashboard';
import PackageBuilder from './pages/admin/PackageBuilder';
import CandidateTracker from './pages/admin/CandidateTracker';

// Portal Pages
import Login from './pages/portal/Login';
import TestDashboard from './pages/portal/TestDashboard';
import TestRunner from './pages/portal/TestRunner';

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Root redirect */}
          <Route path="/" element={<Navigate to="/admin" replace />} />

          {/* Admin auth */}
          <Route path="/admin/login" element={<AdminLogin />} />

          {/* Admin Routes (protected by Supabase Auth) */}
          <Route
            path="/admin"
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="packages/create" element={<PackageBuilder />} />
            <Route path="candidates" element={<CandidateTracker />} />
          </Route>

          {/* Portal Routes (candidate access-code flow) */}
          <Route path="/portal" element={<PortalLayout />}>
            <Route index element={<Login />} />
            <Route path="dashboard" element={<TestDashboard />} />
            <Route path="test/:testId" element={<TestRunner />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;

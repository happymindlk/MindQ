import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { AuthProvider } from './context/AuthContext.jsx';
import ProtectedRoute from './components/ProtectedRoute';

import Layout from './components/Layout';
import PortalLayout from './components/PortalLayout';

import AdminLogin from './pages/admin/Login';
import Dashboard from './pages/admin/Dashboard';
import Corporates from './pages/admin/Corporates';
import AssessmentLibrary from './pages/admin/AssessmentLibrary';
import PackageBuilder from './pages/admin/PackageBuilder';
import CandidateTracker from './pages/admin/CandidateTracker';

import Login from './pages/portal/Login';
import Guidelines from './pages/portal/Guidelines';
import TestDashboard from './pages/portal/TestDashboard';
import TestRunner from './pages/portal/TestRunner';

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/admin" replace />} />

          <Route path="/admin/login" element={<AdminLogin />} />

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
            <Route path="library" element={<AssessmentLibrary />} />
            <Route path="packages/create" element={<PackageBuilder />} />
            <Route path="track" element={<CandidateTracker />} />
            <Route path="candidates" element={<Navigate to="/admin/track" replace />} />
          </Route>

          <Route
            path="/track/:packageId"
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<CandidateTracker />} />
          </Route>

          <Route path="/portal" element={<PortalLayout />}>
            <Route index element={<Login />} />
            <Route path="guidelines" element={<Guidelines />} />
            <Route path="dashboard" element={<TestDashboard />} />
            <Route path="test/:testId" element={<TestRunner />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;

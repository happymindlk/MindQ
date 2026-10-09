// Thin FastAPI service client for the candidate flow, reports, and chat.
// HR admin data access lives in src/lib/adminApi.js (supabase-js + RLS).
const API_BASE = `${import.meta.env.VITE_API_URL || ''}/api/v1`;

const getAuthHeaders = () => {
  const token = localStorage.getItem('candidateToken');
  return {
    'Content-Type': 'application/json',
    ...(token && { Authorization: `Bearer ${token}` }),
  };
};

const handleResponse = async (response) => {
  if (!response.ok) {
    let errorMessage = 'An error occurred';
    let errorCode = null;
    try {
      const errorData = await response.json();
      // FastAPI returns errors under `detail`; structured ones carry {code, message}.
      if (typeof errorData.detail === 'string') {
        errorMessage = errorData.detail;
      } else if (Array.isArray(errorData.detail) && errorData.detail[0]?.msg) {
        errorMessage = errorData.detail[0].msg;
      } else if (errorData.detail && typeof errorData.detail === 'object') {
        errorMessage = errorData.detail.message || errorMessage;
        errorCode = errorData.detail.code || null;
      } else if (errorData.message) {
        errorMessage = errorData.message;
      }
    } catch {
      // non-JSON error body; keep default
    }
    const error = new Error(errorMessage);
    error.status = response.status;
    error.code = errorCode;
    throw error;
  }
  return response.json();
};

export const api = {
  candidate: {
    /**
     * @param {{ access_code: string, first_name: string, full_name: string, email: string }} credentials
     * @param {string} emailVerificationToken Supabase OTP access token for `credentials.email`.
     */
    login: async (credentials, emailVerificationToken) => {
      const res = await fetch(`${API_BASE}/candidate/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${emailVerificationToken}`,
        },
        body: JSON.stringify(credentials),
      });
      return handleResponse(res);
    },
    getDashboard: async () => {
      const res = await fetch(`${API_BASE}/candidate/dashboard`, { headers: getAuthHeaders() });
      return handleResponse(res);
    },
    getTest: async (assessmentId) => {
      const res = await fetch(`${API_BASE}/candidate/test/${assessmentId}`, { headers: getAuthHeaders() });
      return handleResponse(res);
    },
    autosave: async (data) => {
      const res = await fetch(`${API_BASE}/candidate/autosave`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(data),
      });
      return handleResponse(res);
    },
    submitTest: async (assessmentId, responses = [], totalModuleDurationSeconds = null) => {
      const res = await fetch(`${API_BASE}/candidate/test/${assessmentId}/submit`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          responses,
          total_module_duration_seconds: totalModuleDurationSeconds,
        }),
      });
      const data = await handleResponse(res);
      return { ...data, status: res.status };
    },
  },
  chat: {
    sendMessage: async (message) => {
      const res = await fetch(`${API_BASE}/chat/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });
      return handleResponse(res);
    },
  },
};

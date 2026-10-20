// Thin FastAPI service client for the candidate flow, reports, and chat.
// HR admin data access lives in src/lib/adminApi.js (supabase-js + RLS).
import { API_ORIGIN } from '../lib/api-origin';

const API_BASE = `${API_ORIGIN}/api/v1`;

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
     * @param {{ access_code: string, email: string, first_name: string, full_name: string }} target
     * @returns {Promise<{ status: string, temp_token: string }>}
     */
    sendCandidateOtp: async (target) => {
      // #region agent log
      fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'605235'},body:JSON.stringify({sessionId:'605235',runId:'pre-fix',hypothesisId:'A,D',location:'client.js:sendCandidateOtp',message:'candidate otp send url',data:{url:`${API_BASE}/candidates/auth/otp/send`,apiOrigin:API_ORIGIN,payloadKeys:Object.keys(target||{})},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      const res = await fetch(`${API_BASE}/candidates/auth/otp/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(target),
      });
      return handleResponse(res);
    },
    /**
     * @param {{ access_code: string, first_name: string, full_name: string, email: string, temp_token: string, otp_code: string }} credentials
     */
    verifyCandidateOtp: async (credentials) => {
      // #region agent log
      fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'605235'},body:JSON.stringify({sessionId:'605235',runId:'pre-fix',hypothesisId:'A,D',location:'client.js:verifyCandidateOtp',message:'candidate otp verify url',data:{url:`${API_BASE}/candidates/auth/otp/verify`,apiOrigin:API_ORIGIN},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      const res = await fetch(`${API_BASE}/candidates/auth/otp/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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

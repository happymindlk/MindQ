import { useContext } from 'react';
import { ClientSessionContext } from './client-session-context';

export function useClientSession() {
  const ctx = useContext(ClientSessionContext);
  if (!ctx) throw new Error('useClientSession must be used within ClientSessionProvider');
  return ctx;
}

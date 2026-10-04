import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import BackendGate from '@/components/BackendGate';
import { AuthProvider } from '@/hooks/useAuth';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BackendGate>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BackendGate>
  </StrictMode>,
);

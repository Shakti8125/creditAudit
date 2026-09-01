import { useCallback, useEffect, useState } from 'react';
import { UserProfile } from '@/types';
import { apiFetch } from '@/lib/http';
import { clearTokens, getAccessToken, setTokens } from '@/lib/auth';

export interface AuthState {
  user: UserProfile | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, tenantName: string) => Promise<void>;
  logout: () => void;
}

interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

interface UserDto {
  id: string;
  email: string;
  full_name?: string;
  title?: string;
  division?: string;
  security_clearance?: string;
  role: string;
  is_active: boolean;
}

function mapUser(dto: UserDto): UserProfile {
  return {
    id: dto.id,
    email: dto.email,
    fullName: dto.full_name,
    title: dto.title,
    division: dto.division,
    securityClearance: dto.security_clearance,
    role: dto.role,
    isActive: dto.is_active,
  };
}

export default function useAuth(): AuthState {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function bootstrap() {
      if (!getAccessToken()) {
        if (mounted) setReady(true);
        return;
      }
      try {
        const dto = await apiFetch<UserDto>('/users/me');
        if (mounted) setUser(mapUser(dto));
      } catch {
        clearTokens();
        if (mounted) setUser(null);
      } finally {
        if (mounted) setReady(true);
      }
    }

    void bootstrap();

    return () => {
      mounted = false;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await apiFetch<AuthTokenResponse>('/auth/login', {
      method: 'POST',
      body: { email, password },
    });
    setTokens(tokens.access_token, tokens.refresh_token);
    const dto = await apiFetch<UserDto>('/users/me');
    setUser(mapUser(dto));
  }, []);

  const register = useCallback(
    async (email: string, password: string, tenantName: string) => {
      const tokens = await apiFetch<AuthTokenResponse>('/auth/register', {
        method: 'POST',
        body: { email, password, tenant_name: tenantName },
      });
      setTokens(tokens.access_token, tokens.refresh_token);
      const dto = await apiFetch<UserDto>('/users/me');
      setUser(mapUser(dto));
    },
    [],
  );

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
  }, []);

  return { user, ready, login, register, logout };
}
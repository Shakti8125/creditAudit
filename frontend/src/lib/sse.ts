import { getAccessToken } from '@/lib/auth';
import { ApiError } from '@/lib/http';

const BASE =
  ((import.meta as any).env.VITE_API_BASE_URL as string | undefined) || '/api';

export interface QueryStreamHandlers {
  onSessionId?: (id: string) => void;
  onCitations?: (citations: any[]) => void;
  onToken?: (token: string) => void;
  onSuggestedActions?: (actions: string[]) => void;
  onDone?: () => void;
  onError?: (message: string) => void;
}

export async function streamQuery(
  body: { question: string; documentId?: string; sessionId?: string },
  handlers: QueryStreamHandlers,
): Promise<void> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const token = getAccessToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${BASE}/query`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      question: body.question,
      document_id: body.documentId ?? null,
      session_id: body.sessionId ?? null,
    }),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      if (
        data &&
        typeof data === 'object' &&
        typeof data.detail === 'string' &&
        data.detail
      ) {
        detail = data.detail;
      }
    } catch {
      // Ignore body parse failures; fall back to status text.
    }
    throw new ApiError(response.status, detail);
  }

  if (!response.body) {
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const dispatch = (payload: any) => {
    switch (payload?.type) {
      case 'session_id':
        handlers.onSessionId?.(payload.content);
        break;
      case 'citations':
        handlers.onCitations?.(payload.content);
        break;
      case 'token':
        handlers.onToken?.(payload.content);
        break;
      case 'suggestedActions':
        handlers.onSuggestedActions?.(payload.content);
        break;
      case 'done':
        handlers.onDone?.();
        break;
      case 'error':
        handlers.onError?.(payload.content);
        break;
      default:
        break;
    }
  };

  const consume = () => {
    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data:')) {
          continue;
        }
        const raw = line.slice(5).trim();
        if (!raw) {
          continue;
        }
        try {
          dispatch(JSON.parse(raw));
        } catch {
          // Skip unparseable lines.
        }
      }
      boundary = buffer.indexOf('\n\n');
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    consume();
  }

  buffer += decoder.decode();
  consume();
}
/**
 * Turns a failed API call into the message the user sees (PR-03).
 *
 * POST /compare and POST /gap-analysis fail with a typed body, `{detail, code, retryable}`
 * (see `ApiError`). Each code gets wording that says what happened and what to do, and never
 * blames the user for a provider failure. A failure without a code (a network error, a 404, an
 * unexpected 500) gets wording from its status. The server's `detail` is only shown when the
 * code is unknown, because for the privacy and safety codes it can quote the blocked content.
 */
import { ApiError } from '@/lib/http';

/** A failed call, ready to render. */
export interface FailureInfo {
  /** Short headline, e.g. "AI gap analysis failed". */
  title: string;
  /** What happened and what to do next. */
  message: string;
  /** Whether a retry may succeed (the server's flag, or inferred from the status). */
  retryable: boolean;
  /** Typed error code from the server, when it sent one. */
  code?: string;
  /** HTTP status, when the server answered. */
  status?: number;
}

/** A failed AI gap analysis, tied to the document it ran on. */
export interface GapFailure {
  documentId: string;
  failure: FailureInfo;
}

interface FailureContext {
  /** What was being attempted, as a noun phrase: "AI gap analysis", "document comparison". */
  subject: string;
  /** Overrides the default headline `<Subject> failed`. */
  title?: string;
  /** What the safety check looked at, e.g. "the document". Defaults to "the request". */
  input?: string;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Wording for a typed error code; undefined for a code this client does not know. */
function messageForCode(code: string, input: string): string | undefined {
  switch (code) {
    case 'structured_output_invalid':
      return 'The AI returned a response in the wrong format, so there is no result to show. This is usually temporary. Please retry.';
    case 'structured_output_truncated':
      return 'The AI response was cut off before it finished, so it was discarded instead of being shown incomplete. Please retry.';
    case 'provider_unavailable':
      return 'The AI service is not available right now, so the request could not be completed. This is not a problem with your document. Please retry in a moment. If it keeps failing, the AI provider keys or the network connection need attention.';
    case 'output_guardrail_blocked':
      return 'The AI answer did not pass the safety check and was withheld, so there is no result to show. Retrying often gives a valid answer.';
    case 'generation_failed':
      return 'The AI could not complete this request because of an unexpected error. Please retry.';
    case 'input_guardrail_blocked':
      return `The request was blocked by the safety check and was not sent to the AI. Retrying will not change this unless ${input} changes.`;
    case 'egress_blocked':
      return 'The request was blocked by the privacy check: the text prepared for the AI still contained information that must not leave the app, so nothing was sent to the AI provider. Retrying will not change this.';
    default:
      return undefined;
  }
}

/** Wording and retryability for a failure that carries no known code. */
function fromStatus(err: unknown): { message: string; retryable: boolean; status?: number } {
  if (!(err instanceof ApiError)) {
    return {
      message:
        'The request did not reach the server. Check that the backend is running and that you are online, then retry.',
      retryable: true,
    };
  }
  const { status, detail } = err;
  if (status === 401) {
    return { message: 'Your session has expired. Sign in again to continue.', retryable: false, status };
  }
  if (status === 403) {
    return { message: 'You do not have permission to do this.', retryable: false, status };
  }
  if (status === 404) {
    return {
      message: `${detail || 'Not found'}. It may have been deleted; reload the page.`,
      retryable: false,
      status,
    };
  }
  if (status === 429) {
    return { message: 'Too many requests right now. Wait a few seconds, then retry.', retryable: true, status };
  }
  if (status >= 500) {
    return { message: `The server hit an unexpected error (HTTP ${status}). Please retry.`, retryable: true, status };
  }
  return { message: detail || `The request failed (HTTP ${status}).`, retryable: false, status };
}

/**
 * Describes a failed call for the UI.
 *
 * @param err - What the call threw: an `ApiError`, or a network error from `fetch`.
 * @param context - What was being attempted.
 */
export function describeFailure(err: unknown, context: FailureContext): FailureInfo {
  const title = context.title ?? `${capitalize(context.subject)} failed`;
  const apiError = err instanceof ApiError ? err : null;

  if (apiError?.code) {
    const message = messageForCode(apiError.code, context.input ?? 'the request');
    if (message) {
      return {
        title,
        message,
        // A typed error always says whether a retry can help.
        retryable: apiError.retryable ?? false,
        code: apiError.code,
        status: apiError.status,
      };
    }
    // A code from a newer server: show its own text rather than guessing.
    return {
      title,
      message: apiError.detail || 'The request failed.',
      retryable: apiError.retryable ?? apiError.status >= 500,
      code: apiError.code,
      status: apiError.status,
    };
  }

  const inferred = fromStatus(err);
  return {
    title,
    message: inferred.message,
    retryable: apiError?.retryable ?? inferred.retryable,
    status: inferred.status,
  };
}

import { useEffect, useRef, useState } from 'react';
import { Check, Loader2, ThumbsDown, ThumbsUp } from 'lucide-react';
import { ApiError } from '@/lib/http';
import { deleteRagFeedback, submitRagFeedback } from '@/lib/ragApi';
import type { FeedbackTag } from '@/lib/ragTypes';
import { FEEDBACK_TAGS, TAG_LABEL, errorMessage } from '@/lib/ragFormat';

type Rating = 1 | -1 | null;

interface FeedbackControlProps {
  traceId: string;
  initialRating?: Rating;
  compact?: boolean;
  /** Called after the server accepted a change (e.g. so a parent can refresh counts). */
  onChange?: (rating: Rating) => void;
}

const MAX_COMMENT = 1000;

const baseBtn =
  'inline-flex items-center gap-1 px-2 py-1 rounded-full border text-xs font-semibold transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-60';
const idleBtn = 'border-slate-200 bg-white text-slate-500 hover:border-indigo-300';
const upActive = 'text-indigo-700 bg-indigo-50 border-indigo-200';
const downActive = 'text-rose-700 bg-rose-50 border-rose-200';

/**
 * Thumbs up / down on a RAG trace. Optimistic with rollback; clicking the active rating
 * again clears the vote. A thumbs-down opens an optional tags + comment panel.
 */
export default function FeedbackControl({
  traceId,
  initialRating = null,
  compact = false,
  onChange,
}: FeedbackControlProps) {
  const [rating, setRating] = useState<Rating>(initialRating ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [tags, setTags] = useState<FeedbackTag[]>([]);
  const [comment, setComment] = useState('');
  const [thanks, setThanks] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // New trace: reset everything.
  useEffect(() => {
    setPanelOpen(false);
    setTags([]);
    setComment('');
    setError(null);
    setThanks(false);
  }, [traceId]);

  // Keep in sync with the server value supplied by a parent.
  useEffect(() => {
    setRating(initialRating ?? null);
  }, [traceId, initialRating]);

  async function run(next: Rating, action: () => Promise<unknown>, after?: () => void) {
    const prev = rating;
    setRating(next);
    setBusy(true);
    setError(null);
    setThanks(false);
    try {
      await action();
      if (!mounted.current) return;
      after?.();
      onChange?.(next);
    } catch (err) {
      if (!mounted.current) return;
      // Clearing a vote that is already gone is a success.
      if (next === null && err instanceof ApiError && err.status === 404) {
        onChange?.(null);
        return;
      }
      setRating(prev);
      setError(errorMessage(err, 'Could not save feedback'));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  function clickUp() {
    if (busy) return;
    setPanelOpen(false);
    if (rating === 1) {
      void run(null, () => deleteRagFeedback(traceId));
    } else {
      void run(1, () => submitRagFeedback({ trace_id: traceId, rating: 1 }));
    }
  }

  function clickDown() {
    if (busy) return;
    if (rating === -1) {
      setPanelOpen(false);
      void run(null, () => deleteRagFeedback(traceId));
    } else {
      void run(-1, () => submitRagFeedback({ trace_id: traceId, rating: -1 }), () => {
        setTags([]);
        setComment('');
        setPanelOpen(true);
      });
    }
  }

  function sendDetails() {
    if (busy) return;
    const trimmed = comment.trim();
    void run(
      -1,
      () =>
        submitRagFeedback({
          trace_id: traceId,
          rating: -1,
          tags,
          comment: trimmed ? trimmed : null,
        }),
      () => {
        setPanelOpen(false);
        setThanks(true);
      },
    );
  }

  function toggleTag(tag: FeedbackTag) {
    setTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));
  }

  return (
    <div className="text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        {!compact && <span className="mr-1 font-semibold text-slate-500">Was this helpful?</span>}
        <button
          type="button"
          onClick={clickUp}
          disabled={busy}
          aria-pressed={rating === 1}
          title={rating === 1 ? 'Remove helpful rating' : 'Helpful'}
          aria-label={rating === 1 ? 'Remove helpful rating' : 'Mark answer as helpful'}
          className={`${baseBtn} ${rating === 1 ? upActive : idleBtn}`}
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={clickDown}
          disabled={busy}
          aria-pressed={rating === -1}
          title={rating === -1 ? 'Remove not-helpful rating' : 'Not helpful'}
          aria-label={rating === -1 ? 'Remove not-helpful rating' : 'Mark answer as not helpful'}
          className={`${baseBtn} ${rating === -1 ? downActive : idleBtn}`}
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </button>
        {busy && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" aria-label="Saving" />}
        {thanks && !busy && (
          <span className="inline-flex items-center gap-1 font-medium text-emerald-700" role="status">
            <Check className="h-3.5 w-3.5" />
            Thanks — feedback recorded.
          </span>
        )}
      </div>

      {error && (
        <p className="mt-1 text-[11px] font-medium text-rose-600" role="alert">
          {error}
        </p>
      )}

      {panelOpen && (
        <div className="mt-2 max-w-md space-y-2.5 rounded-2xl border border-slate-200 bg-white p-3 shadow-xs">
          <p className="font-semibold text-slate-700">What went wrong? (optional)</p>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Feedback tags">
            {FEEDBACK_TAGS.map((tag) => {
              const on = tags.includes(tag);
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggleTag(tag)}
                  className={`cursor-pointer rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                    on
                      ? 'border-rose-200 bg-rose-50 text-rose-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                  }`}
                >
                  {on && <Check className="-ml-0.5 mr-0.5 inline h-3 w-3" />}
                  {TAG_LABEL[tag]}
                </button>
              );
            })}
          </div>
          <div>
            <label className="sr-only" htmlFor={`fb-comment-${traceId}`}>
              Comment
            </label>
            <textarea
              id={`fb-comment-${traceId}`}
              value={comment}
              maxLength={MAX_COMMENT}
              onChange={(e) => setComment(e.target.value.slice(0, MAX_COMMENT))}
              rows={3}
              placeholder="Add a comment (identifiers are masked before storage)"
              className="w-full resize-y rounded-xl border border-slate-200 px-3 py-2 text-xs text-slate-800 placeholder:text-slate-400 focus:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-600/20"
            />
            <div className="mt-0.5 text-right text-[10px] tabular-nums text-slate-400">
              {comment.length}/{MAX_COMMENT}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setPanelOpen(false)}
              disabled={busy}
              className="cursor-pointer rounded-full px-3 py-1 text-xs font-semibold text-slate-500 hover:bg-slate-100 disabled:opacity-60"
            >
              Skip
            </button>
            <button
              type="button"
              onClick={sendDetails}
              disabled={busy}
              className="cursor-pointer rounded-full bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-60"
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * RecentActivity — clickable detection event list with inline detail panels.
 *
 * Polls GET /api/status/events every 15 seconds via React Query and renders
 * an accordion-style list of the 20 most recent detection events.  Clicking
 * a row expands a detail panel showing the full pipeline breakdown for that
 * event (TTS message, escalation, AI provider, latency, etc.).
 *
 * Design rules applied:
 *  - Dark-first surface matching the rest of the dashboard
 *  - Only one row expanded at a time (accordion)
 *  - Score colour-coded: green ≥ 80 %, amber ≥ 60 %, red < 60 %
 *  - Response mode as a coloured pill badge
 *  - Null / missing fields are silently omitted — no "N/A" noise
 *  - Smooth CSS transition on expand / collapse
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Camera,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
  Clock,
  Volume2,
  Brain,
  Shield,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { getRecentEvents } from '@/api/status';

/**
 * Clean up raw AI description for display.
 * The AI may return JSON arrays, markdown-fenced JSON, or dispatch JSON objects.
 * This extracts readable text from any of those formats.
 */
function formatAiDescription(raw: string): string {
  const trimmed = raw.trim();

  // Strip markdown fences
  let cleaned = trimmed;
  if (cleaned.startsWith('```')) {
    const lines = cleaned.split('\n');
    const inner = lines.slice(1);
    if (inner.length > 0 && inner[inner.length - 1]?.trim().startsWith('```')) {
      inner.pop();
    }
    cleaned = inner.join('\n').trim();
  }

  // Try JSON array: ["phrase1", "phrase2"]
  try {
    const parsed = JSON.parse(cleaned);
    if (Array.isArray(parsed) && parsed.every((p: unknown) => typeof p === 'string')) {
      return parsed.join(' ');
    }
    // JSON object (dispatch format): extract description + location
    if (typeof parsed === 'object' && parsed !== null) {
      const parts: string[] = [];
      if (parsed.description && parsed.description !== 'unknown') parts.push(parsed.description);
      if (parsed.location && parsed.location !== 'unknown') parts.push(parsed.location);
      if (parsed.behavior) parts.push(parsed.behavior);
      if (parts.length > 0) return parts.join('. ');
    }
  } catch {
    // Not JSON — use as-is
  }

  return cleaned;
}
import type { DetectionEvent } from '@/api/status';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Converts an ISO timestamp string into a short relative string such as
 * "12s ago", "4m ago", or "2h ago". Returns "just now" for future timestamps.
 */
function relativeTime(iso: string): string {
  const delta = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (delta < 0) return 'just now';
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

/** Format score (0–1 float) as a percentage string, e.g. "93%". */
function formatScore(score: number): string {
  return `${Math.round(score * 100)}%`;
}

/** Tailwind text colour classes based on detection score. */
function scoreColor(score: number): string {
  const pct = score * 100;
  if (pct >= 80) return 'text-green-400';
  if (pct >= 60) return 'text-amber-400';
  return 'text-red-400';
}

/**
 * Response mode pill colour mapping.  Falls back to a neutral style for
 * any mode not listed here.
 */
function modeBadgeClass(mode: string): string {
  switch (mode) {
    case 'police_dispatch':
      return 'bg-blue-900/50 text-blue-300 border border-blue-700/50';
    case 'automated_surveillance':
      return 'bg-purple-900/50 text-purple-300 border border-purple-700/50';
    case 'deterrent':
      return 'bg-orange-900/50 text-orange-300 border border-orange-700/50';
    case 'silent':
      return 'bg-gray-700/60 text-gray-400 border border-gray-600/50';
    default:
      return 'bg-gray-700/60 text-gray-300 border border-gray-600/50';
  }
}

/** Human-readable label for a response mode string. */
function modeLabel(mode: string): string {
  return mode.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Format latency milliseconds as a rounded seconds string, e.g. "12.5s". */
function formatLatency(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

// ---------------------------------------------------------------------------
// EventDetail — the expanded content block
// ---------------------------------------------------------------------------

interface EventDetailProps {
  event: DetectionEvent;
}

/**
 * Full pipeline breakdown rendered inside an expanded event row.
 *
 * Each section is conditionally rendered — if the relevant fields are all
 * null or undefined the section is entirely omitted rather than showing
 * placeholder text.
 */
function EventDetail({ event }: EventDetailProps) {
  const hasTts = event.tts_message != null && event.tts_message !== '';
  const hasEscalation =
    event.escalation_ran &&
    (event.escalation_message != null || event.escalation_description != null);
  const hasAiDesc = event.escalation_description != null && event.escalation_description !== '';
  const hasProviders = event.tts_provider != null || event.ai_provider != null;

  return (
    <div className="mt-1 mb-2 mx-1 rounded-xl border border-gray-700/60 bg-gray-900/70 overflow-hidden text-sm">
      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3 border-b border-gray-700/50">
        <div className="flex items-center gap-2 text-gray-200 font-medium">
          <Camera className="h-4 w-4 text-gray-400 flex-shrink-0" aria-hidden="true" />
          {event.camera}
        </div>
        <span className="text-xs text-gray-400">
          {new Date(event.timestamp).toLocaleString()}
        </span>
      </div>

      {/* Metrics bar */}
      <div className="flex flex-wrap items-center gap-4 px-4 py-2 border-b border-gray-700/50 text-xs text-gray-400">
        <span>
          Score:{' '}
          <span className={cn('font-semibold', scoreColor(event.score))}>
            {formatScore(event.score)}
          </span>
        </span>
        <span>
          Mode:{' '}
          <span className="text-gray-200">{modeLabel(event.response_mode)}</span>
        </span>
        {event.total_latency_ms != null && (
          <span>
            Latency:{' '}
            <span className="text-gray-200">{formatLatency(event.total_latency_ms)}</span>
          </span>
        )}
      </div>

      {/* Initial TTS response */}
      {hasTts && (
        <div className="px-4 py-3 border-b border-gray-700/50 space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide">
            <Volume2 className="h-3.5 w-3.5" aria-hidden="true" />
            1. Initial Response
          </div>
          <p className="text-gray-200 leading-relaxed">
            &ldquo;{event.tts_message}&rdquo;
          </p>
          {event.initial_audio_success != null && (
            <div
              className={cn(
                'flex items-center gap-1.5 text-xs font-medium',
                event.initial_audio_success ? 'text-green-400' : 'text-red-400',
              )}
            >
              {event.initial_audio_success ? (
                <CheckCircle className="h-3.5 w-3.5" aria-hidden="true" />
              ) : (
                <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {event.initial_audio_success
                ? 'Audio pushed successfully'
                : 'Audio push failed'}
            </div>
          )}
        </div>
      )}

      {/* AI analysis / scene description */}
      {hasAiDesc && (
        <div className="px-4 py-3 border-b border-gray-700/50 space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide">
            <Brain className="h-3.5 w-3.5" aria-hidden="true" />
            2. AI Analysis
          </div>
          <p className="text-gray-200 leading-relaxed">
            &ldquo;{formatAiDescription(event.escalation_description ?? '')}&rdquo;
          </p>
        </div>
      )}

      {/* Escalation */}
      {hasEscalation && (
        <div className="px-4 py-3 border-b border-gray-700/50 space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide">
            <Shield className="h-3.5 w-3.5" aria-hidden="true" />
            3. Escalation
          </div>
          {event.escalation_message != null && event.escalation_message !== '' && (
            <p className="text-gray-200 leading-relaxed">
              &ldquo;{event.escalation_message}&rdquo;
            </p>
          )}
          {event.escalation_audio_success != null && (
            <div
              className={cn(
                'flex items-center gap-1.5 text-xs font-medium',
                event.escalation_audio_success ? 'text-green-400' : 'text-red-400',
              )}
            >
              {event.escalation_audio_success ? (
                <CheckCircle className="h-3.5 w-3.5" aria-hidden="true" />
              ) : (
                <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {event.escalation_audio_success
                ? 'Audio pushed successfully'
                : 'Audio push failed'}
            </div>
          )}
        </div>
      )}

      {/* TTS / AI provider footer */}
      {hasProviders && (
        <div className="flex flex-wrap items-center gap-4 px-4 py-2.5 text-xs text-gray-500">
          {event.tts_provider != null && (
            <span className="flex items-center gap-1">
              <Volume2 className="h-3 w-3" aria-hidden="true" />
              TTS:{' '}
              <span className="text-gray-400 ml-0.5">
                {event.tts_provider}
                {event.tts_voice != null ? ` / ${event.tts_voice}` : ''}
              </span>
            </span>
          )}
          {event.ai_provider != null && (
            <span className="flex items-center gap-1">
              <Brain className="h-3 w-3" aria-hidden="true" />
              AI:{' '}
              <span className="text-gray-400 ml-0.5">{event.ai_provider}</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EventRow — collapsed summary + optional expanded detail
// ---------------------------------------------------------------------------

interface EventRowProps {
  /** The detection event data. */
  event: DetectionEvent;
  /** Whether this row's detail panel is currently expanded. */
  isExpanded: boolean;
  /** Called when the user clicks the row to toggle expansion. */
  onToggle: () => void;
  /** Whether to show a bottom border separator. */
  showBorder: boolean;
}

/**
 * Single event list item.  In its collapsed state it shows the camera name,
 * response mode badge, score, and relative time.  Clicking it expands an
 * inline EventDetail panel below the row summary.
 */
function EventRow({ event, isExpanded, onToggle, showBorder }: EventRowProps) {
  const rel = relativeTime(event.timestamp);

  return (
    <li>
      {/* Clickable summary row */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isExpanded}
        className={cn(
          'w-full flex items-center gap-3 px-1 py-3 text-left',
          'transition-colors duration-150 rounded-lg',
          'hover:bg-gray-800/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
          showBorder && !isExpanded && 'border-b border-gray-800/50',
        )}
      >
        {/* Camera icon */}
        <Camera
          className="h-4 w-4 flex-shrink-0 text-gray-500"
          aria-hidden="true"
        />

        {/* Camera name */}
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-200">
          {event.camera}
        </span>

        {/* Score */}
        <span
          className={cn(
            'flex-shrink-0 text-xs font-semibold tabular-nums',
            scoreColor(event.score),
          )}
        >
          {formatScore(event.score)}
        </span>

        {/* Mode badge */}
        <span
          className={cn(
            'hidden sm:inline-flex flex-shrink-0 rounded-full px-2 py-0.5 text-xs font-medium',
            modeBadgeClass(event.response_mode),
          )}
        >
          {modeLabel(event.response_mode)}
        </span>

        {/* Relative time */}
        <span className="flex-shrink-0 flex items-center gap-1 text-xs text-gray-500">
          <Clock className="h-3 w-3" aria-hidden="true" />
          {rel}
        </span>

        {/* Expand/collapse chevron */}
        {isExpanded ? (
          <ChevronUp className="h-4 w-4 flex-shrink-0 text-gray-500" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-4 w-4 flex-shrink-0 text-gray-500" aria-hidden="true" />
        )}
      </button>

      {/* Inline detail panel — rendered below the row when expanded */}
      {isExpanded && <EventDetail event={event} />}
    </li>
  );
}

// ---------------------------------------------------------------------------
// RecentActivity — main export
// ---------------------------------------------------------------------------

/**
 * Polls /api/status/events every 15 s and renders a clickable accordion list
 * of the 20 most recent detection events.
 */
export function RecentActivity() {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: events, isLoading } = useQuery({
    queryKey: ['recent-events'],
    queryFn: () => getRecentEvents(20),
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  /** Toggle a row open; close it if already expanded. */
  function handleToggle(eventId: string) {
    setExpandedId((prev) => (prev === eventId ? null : eventId));
  }

  return (
    <div className="rounded-2xl bg-white dark:bg-gray-900/80 border border-gray-200 dark:border-gray-800/60 p-5 space-y-3 transition-all duration-200">
      {/* Section header */}
      <div className="flex items-center gap-2">
        <Shield className="h-4 w-4 text-gray-500 dark:text-gray-400" aria-hidden="true" />
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 dark:text-gray-400">
          Recent Detections
        </h3>
        <span className="text-[10px] text-gray-600 dark:text-gray-600 italic">
          click for details
        </span>
      </div>

      {/* Loading skeleton */}
      {isLoading && (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded-xl bg-gray-100 dark:bg-gray-800/50"
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && (!events || events.length === 0) && (
        <div className="flex flex-col items-center justify-center gap-2 py-8 text-gray-500 dark:text-gray-600">
          <Shield className="h-8 w-8" aria-hidden="true" />
          <p className="text-sm">No recent detections</p>
        </div>
      )}

      {/* Event list */}
      {!isLoading && events && events.length > 0 && (
        <ul className="space-y-0">
          {events.map((event, idx) => (
            <EventRow
              key={event.event_id}
              event={event}
              isExpanded={expandedId === event.event_id}
              onToggle={() => handleToggle(event.event_id)}
              showBorder={idx < events.length - 1}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

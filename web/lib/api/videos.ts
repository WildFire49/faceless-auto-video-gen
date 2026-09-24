/**
 * Video queue hooks and the shared display helpers for statuses and gates.
 *
 * LAYER 3 (cross-cutting) of SPEC.md 14.1. Query keys and label mappings live
 * here rather than in components, so that every screen shows the same wording
 * for the same state and a cache invalidation can never miss a key.
 */

'use client';

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import { rewindClient, videoClient } from './client';
import { Gate, VideoStatus, type Video } from '@/lib/gen/rewind/v1/video_pb';
import { palette } from '@/theme/tokens';

export const videoKeys = {
  all: ['videos'] as const,
  list: (needsReviewOnly: boolean) => ['videos', { needsReviewOnly }] as const,
  detail: (id: string) => ['videos', id] as const,
  reviewLog: (id: string) => ['videos', id, 'reviewLog'] as const,
};

/** List the queue. */
export function useVideos(needsReviewOnly = false): UseQueryResult<Video[], Error> {
  return useQuery({
    queryKey: videoKeys.list(needsReviewOnly),
    queryFn: async () => {
      const res = await videoClient.listVideos({ needsReviewOnly });
      return res.videos;
    },
    // The queue changes when a pipeline step finishes, which this app does not
    // observe directly yet, so a slow poll keeps it honest without hammering
    // the API. SSE replaces this in M2 (SPEC.md 8.3).
    refetchInterval: 5_000,
  });
}

/** Queue a new topic, then refresh every list. */
export function useAddVideo() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: { topic: string; priority?: number; notes?: string }) =>
      videoClient.addVideo({
        topic: input.topic,
        priority: input.priority ?? 0,
        notes: input.notes ?? '',
      }),
    // Invalidating the whole 'videos' prefix rather than one key means a new
    // video shows up in the filtered view too, not just the one in front of us.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: videoKeys.all }),
  });
}

/* ------------------------------------------------------------------ labels */

/**
 * Human wording for each status.
 *
 * The wire values are readable enough to debug with, but "storyboard_ready"
 * is not what a person should read in a table.
 */
const STATUS_LABELS: Partial<Record<VideoStatus, string>> = {
  [VideoStatus.QUEUED]: 'Queued',
  [VideoStatus.RESEARCHING]: 'Researching',
  [VideoStatus.FACTS_READY]: 'Facts ready',
  [VideoStatus.FACTS_APPROVED]: 'Facts approved',
  [VideoStatus.FINDING_REFS]: 'Finding references',
  [VideoStatus.REFS_READY]: 'References ready',
  [VideoStatus.REFS_APPROVED]: 'References approved',
  [VideoStatus.SCRIPTING]: 'Writing script',
  [VideoStatus.SCRIPT_READY]: 'Script ready',
  [VideoStatus.SCRIPT_APPROVED]: 'Script approved',
  [VideoStatus.VOICING]: 'Recording voice',
  [VideoStatus.VOICE_READY]: 'Voice ready',
  [VideoStatus.VOICE_APPROVED]: 'Voice approved',
  [VideoStatus.IMAGING]: 'Generating images',
  [VideoStatus.STORYBOARD_READY]: 'Storyboard ready',
  [VideoStatus.STORYBOARD_APPROVED]: 'Storyboard approved',
  [VideoStatus.RENDERING]: 'Rendering',
  [VideoStatus.RENDER_READY]: 'Render ready',
  [VideoStatus.FINAL_APPROVED]: 'Final approved',
  [VideoStatus.UPLOADING]: 'Uploading',
  [VideoStatus.UPLOADED_PRIVATE]: 'Uploaded (private)',
  [VideoStatus.PUBLISHED]: 'Published',
  [VideoStatus.ANALYTICS_COLLECTED]: 'Analytics collected',
  [VideoStatus.ERROR]: 'Failed',
};

export function statusLabel(status: VideoStatus): string {
  return STATUS_LABELS[status] ?? 'Unknown';
}

const GATE_LABELS: Partial<Record<Gate, string>> = {
  [Gate.A_FACTS]: 'A — Facts',
  [Gate.B_REFERENCES]: 'B — References',
  [Gate.C_SCRIPT]: 'C — Script',
  [Gate.D_VOICE]: 'D — Voice',
  [Gate.E_STORYBOARD]: 'E — Storyboard',
  [Gate.F_FINAL]: 'F — Final video',
};

export function gateLabel(gate: Gate): string {
  return GATE_LABELS[gate] ?? '';
}

/** Gate letters in pipeline order, for progress indicators. */
export const GATE_ORDER: Gate[] = [
  Gate.A_FACTS,
  Gate.B_REFERENCES,
  Gate.C_SCRIPT,
  Gate.D_VOICE,
  Gate.E_STORYBOARD,
  Gate.F_FINAL,
];

/** The status each gate's approval moves a video to, in GATE_ORDER. */
const APPROVED_STATUS: VideoStatus[] = [
  VideoStatus.FACTS_APPROVED,
  VideoStatus.REFS_APPROVED,
  VideoStatus.SCRIPT_APPROVED,
  VideoStatus.VOICE_APPROVED,
  VideoStatus.STORYBOARD_APPROVED,
  VideoStatus.FINAL_APPROVED,
];

/**
 * How many gates a video has passed.
 *
 * Relies on the wire enum being ordered along the pipeline -- true for every
 * status EXCEPT ERROR, which is numbered last (24) and so compared as "past
 * every gate". For three milestones every failed video in the queue showed six
 * green dots: failure rendered as complete. A failed video is judged by where
 * it failed (`retryFrom`), not by its error status.
 */
export function gatesPassed(video: Video): number {
  const where = video.status === VideoStatus.ERROR ? video.retryFrom : video.status;
  return APPROVED_STATUS.filter((approved) => where >= approved).length;
}

/** The page that reviews each gate, for gates whose page exists. */
export const GATE_PAGES: Partial<Record<Gate, string>> = {
  [Gate.A_FACTS]: 'facts',
  [Gate.B_REFERENCES]: 'references',
  [Gate.C_SCRIPT]: 'script',
};

/**
 * Where clicking a video should take you: the gate waiting for you, or else
 * the most recent gate you already approved, so a decision can be looked at
 * again. Null when there is nothing to show yet.
 */
export function reviewRouteOf(video: Video): string | null {
  const waiting = GATE_PAGES[video.awaitingGate];
  if (waiting) return `/v/${video.id}/${waiting}`;

  for (let i = gatesPassed(video) - 1; i >= 0; i -= 1) {
    const gate = GATE_ORDER[i];
    const page = gate === undefined ? undefined : GATE_PAGES[gate];
    if (page) return `/v/${video.id}/${page}`;
  }
  return null;
}

/**
 * Whether a gate's sheet can still be changed. Mirrors the API's rule
 * (domain.RequireOpenGate): only while the video waits at that gate. The API
 * is what enforces it; this only keeps the UI from offering what it would
 * refuse.
 */
export function isGateOpen(video: Video, gate: Gate): boolean {
  return video.awaitingGate === gate;
}

/** Re-run the step a failed video stopped at. */
export function useRetryVideo() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (videoId: string) => videoClient.retryVideo({ videoId }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: videoKeys.all }),
  });
}

/**
 * What kind of attention a video needs. Drives colour everywhere, so the
 * meaning of a colour is consistent across the app.
 */
export type Attention = 'waiting-on-you' | 'working' | 'failed' | 'done';

export function attentionOf(video: Video): Attention {
  if (video.status === VideoStatus.ERROR) return 'failed';
  if (video.awaitingGate !== Gate.UNSPECIFIED) return 'waiting-on-you';
  if (
    video.status === VideoStatus.UPLOADED_PRIVATE ||
    video.status === VideoStatus.PUBLISHED ||
    video.status === VideoStatus.ANALYTICS_COLLECTED
  ) {
    return 'done';
  }
  return 'working';
}

export function attentionColor(attention: Attention): string {
  switch (attention) {
    case 'waiting-on-you':
      return palette.status.degraded;
    case 'failed':
      return palette.status.down;
    case 'done':
      return palette.status.ok;
    default:
      return palette.status.unknown;
  }
}

/** Relative time, the way a person scanning a queue wants it. */
export function humanAge(rfc3339: string): string {
  if (!rfc3339) return '—';

  const then = new Date(rfc3339).getTime();
  if (Number.isNaN(then)) return '—';

  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

// Re-exported so pages import their data access from one place.
export { rewindClient };

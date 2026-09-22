/**
 * Gate A data access: the fact sheet, and the job that produces it.
 */

'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';

import { factsClient, videoClient } from './client';
import { videoKeys } from './videos';
import type { FactsView } from '@/lib/gen/rewind/v1/facts_pb';
import { JobState, type Job } from '@/lib/gen/rewind/v1/video_pb';

export const factKeys = {
  sheet: (videoId: string) => ['facts', videoId] as const,
  latestJob: (videoId: string) => ['job', 'latest', videoId] as const,
};

/** Load the fact sheet for review. */
export function useFacts(videoId: string): UseQueryResult<FactsView, Error> {
  return useQuery({
    queryKey: factKeys.sheet(videoId),
    queryFn: async () => (await factsClient.getFacts({ videoId })).view!,
    enabled: Boolean(videoId),
  });
}

/**
 * Track the most recent job for a video.
 *
 * Polls only while something is running, so an idle Gate A page makes one
 * request and then stops (SPEC.md 8.3). Reloading the page reattaches to work
 * already in flight rather than losing sight of it.
 */
export function useLatestJob(videoId: string): UseQueryResult<Job | undefined, Error> {
  return useQuery({
    queryKey: factKeys.latestJob(videoId),
    queryFn: async () => (await videoClient.getLatestJob({ videoId })).job,
    enabled: Boolean(videoId),
    refetchInterval: (query) =>
      query.state.data?.state === JobState.RUNNING ? 1_500 : false,
  });
}

/** Start the next pipeline step. */
export function useRunStep(videoId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => videoClient.runStep({ videoId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: factKeys.latestJob(videoId) });
      queryClient.invalidateQueries({ queryKey: videoKeys.all });
    },
  });
}

/**
 * Every Gate A edit, sharing one cache-update path.
 *
 * Each mutation returns the whole recomputed view, so the cache is SET from
 * the response rather than invalidated and refetched. That keeps the approval
 * verdict ("6 of 8 approved") in step with the tick you just clicked, with no
 * flicker in between.
 */
export function useFactMutations(videoId: string) {
  const queryClient = useQueryClient();

  const applyView = (view?: FactsView) => {
    if (view) queryClient.setQueryData(factKeys.sheet(videoId), view);
    // The video's own row does not change, but its gate readiness might, so
    // the queue is refreshed too.
    queryClient.invalidateQueries({ queryKey: videoKeys.all });
  };

  const setApproval = useMutation({
    mutationFn: (input: { factId: string; approved: boolean }) =>
      factsClient.setFactApproval({ videoId, ...input }),
    onSuccess: (res) => applyView(res.view),
  });

  const approveAll = useMutation({
    mutationFn: (approved: boolean) => factsClient.approveAllFacts({ videoId, approved }),
    onSuccess: (res) => applyView(res.view),
  });

  const updateFact = useMutation({
    mutationFn: (input: {
      factId: string;
      yearLabel: string;
      sortYear: number;
      place: string;
      claim: string;
    }) => factsClient.updateFact({ videoId, ...input }),
    onSuccess: (res) => applyView(res.view),
  });

  const deleteFact = useMutation({
    mutationFn: (input: { factId: string; reason: string }) =>
      factsClient.deleteFact({ videoId, ...input }),
    onSuccess: (res) => applyView(res.view),
  });

  const addFact = useMutation({
    mutationFn: (input: {
      yearLabel: string;
      sortYear: number;
      place: string;
      claim: string;
      sourceUrl: string;
      evidence: string;
    }) => factsClient.addFact({ videoId, ...input }),
    onSuccess: (res) => applyView(res.view),
  });

  return { setApproval, approveAll, updateFact, deleteFact, addFact };
}

/** Approve or reject Gate A itself. */
export function useGateDecision(videoId: string) {
  const queryClient = useQueryClient();

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: videoKeys.all });
    queryClient.invalidateQueries({ queryKey: factKeys.sheet(videoId) });
  };

  const approve = useMutation({
    mutationFn: (input: { gate: number; note: string }) =>
      videoClient.approveGate({ videoId, gate: input.gate, note: input.note }),
    onSuccess: refresh,
  });

  const reject = useMutation({
    mutationFn: (input: { gate: number; backTo: number; note: string }) =>
      videoClient.rejectGate({
        videoId,
        gate: input.gate,
        backTo: input.backTo,
        note: input.note,
      }),
    onSuccess: refresh,
  });

  return { approve, reject };
}

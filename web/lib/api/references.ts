/**
 * Gate B data access: the proposed modern comparisons.
 *
 * Mirrors lib/api/facts.ts deliberately — every mutation returns the whole
 * recomputed view, so the cache is SET from the response rather than
 * invalidated and refetched. That keeps "2 of 3 selected" in step with the
 * tick you just clicked, with no flicker in between.
 */

'use client';

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import { referencesClient } from './client';
import { videoKeys } from './videos';
import type { ReferencesView } from '@/lib/gen/rewind/v1/references_pb';

export const referenceKeys = {
  sheet: (videoId: string) => ['references', videoId] as const,
};

/** Load the comparisons for review. */
export function useReferences(videoId: string): UseQueryResult<ReferencesView, Error> {
  return useQuery({
    queryKey: referenceKeys.sheet(videoId),
    queryFn: async () => (await referencesClient.getReferences({ videoId })).view!,
    enabled: Boolean(videoId),
  });
}

/** The bundle of Gate B edits, passed whole to the dialogs that use them. */
export type ReferenceMutations = ReturnType<typeof useReferenceMutations>;

/** Every Gate B edit, sharing one cache-update path. */
export function useReferenceMutations(videoId: string) {
  const queryClient = useQueryClient();

  const applyView = (view?: ReferencesView) => {
    if (view) queryClient.setQueryData(referenceKeys.sheet(videoId), view);
    queryClient.invalidateQueries({ queryKey: videoKeys.all });
  };

  const select = useMutation({
    mutationFn: (input: { proposalId: string; selected: boolean }) =>
      referencesClient.selectProposal({ videoId, ...input }),
    onSuccess: (res) => applyView(res.view),
  });

  const update = useMutation({
    mutationFn: (input: {
      proposalId: string;
      comparison: string;
      whyFunny: string;
      linkedFactId: string;
    }) => referencesClient.updateProposal({ videoId, ...input }),
    onSuccess: (res) => applyView(res.view),
  });

  const remove = useMutation({
    mutationFn: (input: { proposalId: string; reason: string }) =>
      referencesClient.deleteProposal({ videoId, ...input }),
    onSuccess: (res) => applyView(res.view),
  });

  const add = useMutation({
    mutationFn: (input: {
      reference: string;
      comparison: string;
      whyFunny: string;
      linkedFactId: string;
    }) => referencesClient.addProposal({ videoId, ...input }),
    onSuccess: (res) => applyView(res.view),
  });

  return { select, update, remove, add };
}

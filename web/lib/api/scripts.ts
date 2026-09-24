/**
 * Gate C data access: the beat script.
 *
 * Mirrors the other gates: every mutation returns the whole recomputed view,
 * so the cache is SET from the response. That matters more here than anywhere
 * -- an edit comes back with the worker's fresh verdict on the WHOLE script,
 * and the page must show that verdict, not the one from before the edit.
 */

'use client';

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import { scriptsClient } from './client';
import { videoKeys } from './videos';
import type { ScriptView } from '@/lib/gen/rewind/v1/scripts_pb';

export const scriptKeys = {
  view: (videoId: string) => ['script', videoId] as const,
};

/** Load the script for review. */
export function useScript(videoId: string): UseQueryResult<ScriptView, Error> {
  return useQuery({
    queryKey: scriptKeys.view(videoId),
    queryFn: async () => (await scriptsClient.getScript({ videoId })).view!,
    enabled: Boolean(videoId),
  });
}

/** Every Gate C edit, sharing one cache-update path. */
export function useScriptMutations(videoId: string) {
  const queryClient = useQueryClient();

  const applyView = (view?: ScriptView) => {
    if (view) queryClient.setQueryData(scriptKeys.view(videoId), view);
    queryClient.invalidateQueries({ queryKey: videoKeys.all });
  };

  const updateBeat = useMutation({
    mutationFn: (input: {
      n: number;
      voice: string;
      onScreenText: string;
      yearStamp: string;
      /** The beat's COMPLETE list of comparisons after the edit. */
      refIds: string[];
    }) =>
      scriptsClient.updateBeat({ videoId, ...input }),
    onSuccess: (res) => applyView(res.view),
  });

  const chooseTitle = useMutation({
    mutationFn: (title: string) => scriptsClient.chooseTitle({ videoId, title }),
    onSuccess: (res) => applyView(res.view),
  });

  return { updateBeat, chooseTitle };
}

export type ScriptMutations = ReturnType<typeof useScriptMutations>;

/**
 * Gate B route: /v/<videoId>/references
 */

'use client';

import { use } from 'react';

import { GateShell } from '@/features/gates/GateShell';
import { ReferencesGate } from '@/features/gates/references/ReferencesGate';

export default function ReferencesPage({ params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = use(params);

  return (
    <GateShell videoId={videoId} gateLabel="Gate B — References">
      {(video) => <ReferencesGate video={video} />}
    </GateShell>
  );
}

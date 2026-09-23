/**
 * Gate A route: /v/<videoId>/facts
 */

'use client';

import { use } from 'react';

import { GateShell } from '@/features/gates/GateShell';
import { FactsGate } from '@/features/gates/facts/FactsGate';

export default function FactsPage({ params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = use(params);

  return (
    <GateShell videoId={videoId} gateLabel="Gate A — Facts">
      {(video) => <FactsGate video={video} />}
    </GateShell>
  );
}

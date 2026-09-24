/**
 * Gate C route: /v/<videoId>/script
 */

'use client';

import { use } from 'react';

import { GateShell } from '@/features/gates/GateShell';
import { ScriptGate } from '@/features/gates/script/ScriptGate';

export default function ScriptPage({ params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = use(params);

  return (
    <GateShell videoId={videoId} gateLabel="Gate C — Script">
      {(video) => <ScriptGate video={video} />}
    </GateShell>
  );
}

/**
 * Gate B — pick the modern comparisons (SPEC.md 5.3, 8.2).
 *
 * The one rule this page exists to make visible: at most three. It is a
 * ceiling on how much of a history video can be "basically a modern brand"
 * before it stops being history, so the count is stated plainly at the top and
 * unselectable cards dim rather than disappear.
 */

'use client';

import AddIcon from '@mui/icons-material/Add';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import LinearProgress from '@mui/material/LinearProgress';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useState } from 'react';

import { AddProposalDialog } from './AddProposalDialog';
import { EditProposalDialog } from './EditProposalDialog';
import { GateBDecisionBar } from './GateBDecisionBar';
import { ProposalCard } from './ProposalCard';
import { useFacts, useLatestJob, useRunStep } from '@/lib/api/facts';
import { useReferenceMutations, useReferences } from '@/lib/api/references';
import type { Proposal } from '@/lib/gen/rewind/v1/relevance_pb';
import { JobState, type Video } from '@/lib/gen/rewind/v1/video_pb';

export function ReferencesGate({ video }: { video: Video }) {
  const videoId = video.id;

  const refs = useReferences(videoId);
  const facts = useFacts(videoId);
  const job = useLatestJob(videoId);
  const runStep = useRunStep(videoId);
  const mutations = useReferenceMutations(videoId);

  const [editing, setEditing] = useState<Proposal | null>(null);
  const [adding, setAdding] = useState(false);

  const running = job.data?.state === JobState.RUNNING;
  const view = refs.data;
  const sheet = view?.sheet;

  // Fact lookup, so each card can show what it attaches to. A comparison that
  // does not belong to its fact is the failure worth catching at this gate.
  const factsById = new Map(
    (facts.data?.sheet?.facts ?? []).map((f) => [f.id, f] as const),
  );

  if (running) {
    const percent = (job.data?.percent ?? 0) * 100;
    return (
      <Paper sx={{ p: 5 }}>
        <Stack spacing={3}>
          <Typography variant="h3" component="h2">
            Finding comparisons for {video.topic}
          </Typography>
          <Typography variant="body1" color="text.secondary">
            {job.data?.stage || 'starting'}…
          </Typography>
          <LinearProgress
            variant={percent > 0 ? 'determinate' : 'indeterminate'}
            value={percent}
            sx={{ height: 6, borderRadius: 3 }}
          />
        </Stack>
      </Paper>
    );
  }

  if (refs.isSuccess && !view?.exists) {
    const failed = job.data?.state === JobState.FAILED;
    return (
      <Paper sx={{ p: 5 }}>
        <Stack spacing={3} alignItems="flex-start">
          <Typography variant="h3" component="h2">
            No comparisons yet
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ maxWidth: '58ch' }}>
            The relevance step reads your curated reference bank and today&apos;s trends, then
            proposes lines tied to the facts you approved. Anything that asserts a claim about a
            brand, or reaches for a subject this channel avoids, is thrown out before you see it.
          </Typography>

          {failed ? <Alert severity="error">{job.data?.error}</Alert> : null}
          {runStep.isError ? <Alert severity="error">{runStep.error.message}</Alert> : null}
          {runStep.data && !runStep.data.started ? (
            <Alert severity="info">{runStep.data.reason}</Alert>
          ) : null}

          <Button variant="contained" onClick={() => runStep.mutate()} disabled={runStep.isPending}>
            {runStep.isPending ? 'Starting…' : 'Find comparisons'}
          </Button>
        </Stack>
      </Paper>
    );
  }

  if (refs.isError) return <Alert severity="error">{refs.error.message}</Alert>;
  if (!sheet || !view) return <LinearProgress />;

  const atLimit = view.selectedCount >= view.maxSelectable;
  const staleIds = new Set(view.staleReferenceIds);
  const generated = sheet.candidatesGenerated;
  const rejected = sheet.candidatesRejected;

  return (
    <Stack spacing={3}>
      {generated > 0 && rejected > 0 ? (
        <Alert severity="info" sx={{ borderRadius: 2 }}>
          The model wrote <strong>{generated}</strong> comparisons;{' '}
          <strong>{rejected}</strong> were thrown out for asserting something about a brand,
          reaching for a forbidden subject, or repeating a reference.
          {sheet.rejections.length > 0 ? (
            <Box component="ul" sx={{ mt: 1, mb: 0, pl: 3 }}>
              {sheet.rejections.slice(0, 3).map((r) => (
                <li key={r}>
                  <Typography variant="body2">{r}</Typography>
                </li>
              ))}
            </Box>
          ) : null}
        </Alert>
      ) : null}

      <Stack direction="row" alignItems="center" justifyContent="space-between" flexWrap="wrap">
        <Typography variant="h3" component="h2">
          {view.selectedCount} of {view.maxSelectable} chosen
        </Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={() => setAdding(true)}>
          Write my own
        </Button>
      </Stack>

      {atLimit ? (
        <Alert severity="success" sx={{ borderRadius: 2 }}>
          That is the limit. Three is the point at which a history video starts sounding like an
          advert — untick one to swap it.
        </Alert>
      ) : null}

      <Stack spacing={2}>
        {sheet.proposals.map((proposal) => {
          const fact = factsById.get(proposal.linkedFactId);
          return (
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              factLabel={fact?.label}
              factClaim={fact?.claim}
              stale={staleIds.has(proposal.id)}
              selectable={!atLimit}
              busy={mutations.select.isPending}
              onToggle={(selected) =>
                mutations.select.mutate({ proposalId: proposal.id, selected })
              }
              onEdit={() => setEditing(proposal)}
              onDelete={() => mutations.remove.mutate({ proposalId: proposal.id, reason: '' })}
            />
          );
        })}
      </Stack>

      {mutations.select.isError ? (
        <Alert severity="warning">{mutations.select.error.message}</Alert>
      ) : null}

      <GateBDecisionBar video={video} view={view} />

      <EditProposalDialog
        proposal={editing}
        onClose={() => setEditing(null)}
        mutations={mutations}
      />
      <AddProposalDialog
        open={adding}
        onClose={() => setAdding(false)}
        facts={facts.data?.sheet?.facts ?? []}
        mutations={mutations}
      />
    </Stack>
  );
}

/**
 * Gate A — review the researched facts (SPEC.md 8.2).
 *
 * The three states this page must handle well:
 *   1. no research yet      -> offer to run it
 *   2. research running     -> live progress, not a dead spinner
 *   3. facts ready          -> review, edit, approve
 */

'use client';

import AddIcon from '@mui/icons-material/Add';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import LinearProgress from '@mui/material/LinearProgress';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useState } from 'react';

import { AddFactDialog } from './AddFactDialog';
import { EditFactDialog } from './EditFactDialog';
import { FactRow } from './FactRow';
import { GateDecisionBar } from './GateDecisionBar';
import { useFactMutations, useFacts, useLatestJob, useRunStep } from '@/lib/api/facts';
import type { Fact } from '@/lib/gen/rewind/v1/research_pb';
import { JobState, type Video } from '@/lib/gen/rewind/v1/video_pb';
import { palette } from '@/theme/tokens';

export function FactsGate({ video }: { video: Video }) {
  const videoId = video.id;

  const facts = useFacts(videoId);
  const job = useLatestJob(videoId);
  const runStep = useRunStep(videoId);
  const mutations = useFactMutations(videoId);

  const [editing, setEditing] = useState<Fact | null>(null);
  const [adding, setAdding] = useState(false);

  const running = job.data?.state === JobState.RUNNING;
  const view = facts.data;
  const sheet = view?.sheet;

  // ---- research is running -------------------------------------------------
  if (running) {
    const percent = (job.data?.percent ?? 0) * 100;
    return (
      <Paper sx={{ p: 5 }}>
        <Stack spacing={3}>
          <Stack spacing={1}>
            <Typography variant="h3" component="h2">
              Researching {video.topic}
            </Typography>
            <Typography variant="body1" color="text.secondary">
              {job.data?.stage || 'starting'}…
            </Typography>
          </Stack>

          <LinearProgress
            // Determinate once the worker reports a percentage; indeterminate
            // before that, rather than a misleading 0%.
            variant={percent > 0 ? 'determinate' : 'indeterminate'}
            value={percent}
            sx={{ height: 6, borderRadius: 3 }}
          />

          <Typography variant="body2" color="text.secondary">
            Fetching sources and extracting dated events. Every claim is checked against the
            source text before it reaches you — this takes a minute or two.
          </Typography>
        </Stack>
      </Paper>
    );
  }

  // ---- nothing researched yet ---------------------------------------------
  if (facts.isSuccess && !view?.exists) {
    const failed = job.data?.state === JobState.FAILED;
    return (
      <Paper sx={{ p: 5 }}>
        <Stack spacing={3} alignItems="flex-start">
          <Stack spacing={1}>
            <Typography variant="h3" component="h2">
              No facts yet
            </Typography>
            <Typography variant="body1" color="text.secondary" sx={{ maxWidth: '56ch' }}>
              Research fetches Wikipedia and any URLs in this video&apos;s notes, extracts dated
              events, and throws away anything it cannot trace back to the source.
            </Typography>
          </Stack>

          {failed ? <Alert severity="error">{job.data?.error}</Alert> : null}
          {runStep.isError ? <Alert severity="error">{runStep.error.message}</Alert> : null}
          {runStep.data && !runStep.data.started ? (
            <Alert severity="info">{runStep.data.reason}</Alert>
          ) : null}

          <Button
            variant="contained"
            onClick={() => runStep.mutate()}
            disabled={runStep.isPending}
          >
            {runStep.isPending ? 'Starting…' : 'Research this topic'}
          </Button>
        </Stack>
      </Paper>
    );
  }

  if (facts.isError) {
    return <Alert severity="error">{facts.error.message}</Alert>;
  }
  if (!sheet) {
    return <LinearProgress />;
  }

  // ---- the fact sheet ------------------------------------------------------
  const rejected = sheet.candidatesRejected;
  const extracted = sheet.candidatesExtracted;

  return (
    <Stack spacing={3}>
      {/* The verifier's own numbers. A high rejection rate is a signal about
          the MODEL, not about the topic — it is the one objective measure of
          how much a given model invents on this exact task. */}
      {extracted > 0 ? (
        <Alert
          severity={rejected > extracted / 2 ? 'warning' : 'info'}
          sx={{ borderRadius: 2 }}
        >
          The model proposed <strong>{extracted}</strong> facts;{' '}
          <strong>{rejected}</strong> were rejected because their evidence could not be found
          in the source.{' '}
          {rejected > extracted / 2
            ? 'That is a lot — this model may be inventing. Worth trying another.'
            : 'The rest are quoted verbatim from the sources below.'}
        </Alert>
      ) : null}

      <Paper sx={{ overflow: 'hidden' }}>
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          sx={{ p: 2.5, gap: 2, flexWrap: 'wrap' }}
        >
          <Typography variant="h3" component="h2">
            {sheet.facts.length} facts
          </Typography>

          <Stack direction="row" spacing={1}>
            <Button
              size="small"
              onClick={() => mutations.approveAll.mutate(true)}
              disabled={mutations.approveAll.isPending}
            >
              Approve all
            </Button>
            <Button
              size="small"
              onClick={() => mutations.approveAll.mutate(false)}
              disabled={mutations.approveAll.isPending}
            >
              Clear all
            </Button>
            <Button size="small" startIcon={<AddIcon />} onClick={() => setAdding(true)}>
              Add a fact
            </Button>
          </Stack>
        </Stack>

        <Divider />

        <Stack divider={<Divider />}>
          {sheet.facts.map((fact) => (
            <FactRow
              key={fact.id}
              fact={fact}
              busy={mutations.setApproval.isPending}
              onToggle={(approved) =>
                mutations.setApproval.mutate({ factId: fact.id, approved })
              }
              onEdit={() => setEditing(fact)}
              onDelete={() =>
                mutations.deleteFact.mutate({ factId: fact.id, reason: '' })
              }
            />
          ))}
        </Stack>
      </Paper>

      <Paper sx={{ p: 2.5 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Sources
        </Typography>
        <Stack spacing={0.5}>
          {sheet.sources.map((source) => (
            <Typography key={source.url} variant="body2">
              <Box component="span" sx={{ color: palette.status.unknown, mr: 1 }}>
                {source.fetcher}
              </Box>
              {source.title}
            </Typography>
          ))}
        </Stack>
      </Paper>

      <GateDecisionBar video={video} view={view} />

      <EditFactDialog
        videoId={videoId}
        fact={editing}
        onClose={() => setEditing(null)}
        mutations={mutations}
      />
      <AddFactDialog
        open={adding}
        onClose={() => setAdding(false)}
        mutations={mutations}
      />
    </Stack>
  );
}

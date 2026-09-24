/**
 * Gate C — review the beat script (SPEC.md 5.4, 8.2).
 *
 * The reviewer's job here is narrower than it looks: the worker has already
 * checked every rule it can. What it cannot judge is whether the script is
 * GOOD -- funny, well paced, true to the facts' spirit rather than just their
 * numbers. So the page puts the narration first, coloured by what each part
 * is, and keeps the rule-checking out of the way unless something is broken.
 */

'use client';

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import LinearProgress from '@mui/material/LinearProgress';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useState } from 'react';

import { BeatRow, KIND_COLOUR } from './BeatRow';
import { EditBeatDialog } from './EditBeatDialog';
import { GateCDecisionBar } from './GateCDecisionBar';
import { TitlePicker } from './TitlePicker';
import { GateClosedBar } from '@/features/gates/GateClosedBar';
import { StepRunning } from '@/features/gates/StepRunning';
import { useFacts, useLatestJob, useRunStep } from '@/lib/api/facts';
import { useReferences } from '@/lib/api/references';
import { useScript, useScriptMutations } from '@/lib/api/scripts';
import { isGateOpen } from '@/lib/api/videos';
import type { Beat } from '@/lib/gen/rewind/v1/script_pb';
import { Gate, JobState, type Video } from '@/lib/gen/rewind/v1/video_pb';
import { opacity, tint } from '@/theme/colour';

function Legend() {
  const items = [
    ['fact', 'Approved fact — hover for its source'],
    ['joke', 'Joke'],
    ['ref', 'Modern comparison'],
  ] as const;
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {items.map(([kind, label]) => (
        <Chip
          key={kind}
          size="small"
          label={label}
          sx={{
            backgroundColor: tint(KIND_COLOUR[kind], opacity.fill),
            border: `1px solid ${tint(KIND_COLOUR[kind], opacity.outline)}`,
          }}
        />
      ))}
    </Stack>
  );
}

export function ScriptGate({ video }: { video: Video }) {
  const videoId = video.id;
  const script = useScript(videoId);
  const facts = useFacts(videoId);
  const refs = useReferences(videoId);
  const job = useLatestJob(videoId);
  const runStep = useRunStep(videoId);
  const mutations = useScriptMutations(videoId);
  const [editing, setEditing] = useState<Beat | null>(null);

  // Closed once approved (or before it is reached); the API refuses edits then.
  const readOnly = !isGateOpen(video, Gate.C_SCRIPT);
  const view = script.data;

  if (job.data?.state === JobState.RUNNING) {
    return <StepRunning title={`Writing the script for ${video.topic}`} job={job.data} />;
  }

  if (script.isSuccess && !view?.exists) {
    return (
      <Paper sx={{ p: 5 }}>
        <Stack spacing={3} alignItems="flex-start">
          <Typography variant="h3" component="h2">
            No script yet
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ maxWidth: '58ch' }}>
            The script writer turns the facts you approved and the comparisons you chose into 9
            beats. Every number it writes must come from a fact that beat cites; a draft that breaks
            a rule is rewritten with the problem pointed out.
          </Typography>
          {job.data?.state === JobState.FAILED ? <Alert severity="error">{job.data.error}</Alert> : null}
          {runStep.isError ? <Alert severity="error">{runStep.error.message}</Alert> : null}
          {runStep.data && !runStep.data.started ? (
            <Alert severity="info">{runStep.data.reason}</Alert>
          ) : null}
          <Button variant="contained" onClick={() => runStep.mutate()} disabled={runStep.isPending}>
            {runStep.isPending ? 'Starting…' : 'Write the script'}
          </Button>
        </Stack>
      </Paper>
    );
  }

  if (script.isError) return <Alert severity="error">{script.error.message}</Alert>;
  if (!view?.script) return <LinearProgress />;

  const s = view.script;
  const factsById = new Map((facts.data?.sheet?.facts ?? []).map((f) => [f.id, f] as const));
  const refsById = new Map((refs.data?.sheet?.proposals ?? []).map((p) => [p.id, p] as const));
  const wholeScript = s.violations.filter((v) => v.beat === 0);

  return (
    <Stack spacing={3}>
      {s.violations.length > 0 && !readOnly ? (
        <Alert severity="warning" sx={{ borderRadius: 2 }}>
          The script writer tried {s.attempts} time{s.attempts === 1 ? '' : 's'} and{' '}
          <strong>{s.violations.length}</strong> rule{s.violations.length === 1 ? ' is' : 's are'}{' '}
          still broken. Fix them below, or rewrite the script.
          {wholeScript.length > 0 ? (
            <Box component="ul" sx={{ mt: 1, mb: 0, pl: 3 }}>
              {wholeScript.map((v) => (
                <li key={v.rule + v.message}>
                  <Typography variant="body2">{v.message}</Typography>
                </li>
              ))}
            </Box>
          ) : null}
        </Alert>
      ) : null}

      <TitlePicker
        options={s.titleOptions}
        chosen={s.chosenTitle}
        readOnly={readOnly}
        mutations={mutations}
      />

      <Legend />

      <Paper>
        <Stack divider={<Divider />}>
          {s.beats.map((beat) => (
            <BeatRow
              key={beat.n}
              beat={beat}
              facts={beat.factIds.flatMap((id) => factsById.get(id) ?? [])}
              refs={beat.refIds.flatMap((id) => refsById.get(id) ?? [])}
              violations={s.violations.filter((v) => v.beat === beat.n)}
              readOnly={readOnly}
              onEdit={() => setEditing(beat)}
            />
          ))}
        </Stack>
      </Paper>

      <Paper sx={{ p: 2.5 }}>
        <Stack spacing={1}>
          <Typography variant="body2" color="text.secondary">
            Description
          </Typography>
          <Typography variant="body1">{s.description || '—'}</Typography>
          <Typography variant="body2" color="text.secondary">
            {s.hashtags.join(' ')}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ pt: 1 }}>
            Sources
          </Typography>
          {s.sources.map((url) => (
            <Link key={url} href={url} target="_blank" rel="noopener noreferrer" variant="body2">
              {url}
            </Link>
          ))}
        </Stack>
      </Paper>

      {readOnly ? (
        <GateClosedBar
          video={video}
          gate={Gate.C_SCRIPT}
          summary={`${s.beats.length} beats, titled “${s.chosenTitle}”.`}
        />
      ) : (
        <GateCDecisionBar video={video} view={view} />
      )}

      <EditBeatDialog
        beat={editing}
        proposals={refs.data?.sheet?.proposals ?? []}
        onClose={() => setEditing(null)}
        mutations={mutations}
      />
    </Stack>
  );
}

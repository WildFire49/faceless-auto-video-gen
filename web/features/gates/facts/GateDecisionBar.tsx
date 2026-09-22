/**
 * GateDecisionBar — approve Gate A, or send the video back.
 *
 * Restraint (SPEC.md 8.1): the approve button is the only filled control on
 * the page, so the primary action is unmistakable. It stays disabled, with the
 * reason stated, until the fact sheet meets the bar — the rule itself is
 * enforced in Go, and this only reports it.
 */

'use client';

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { useGateDecision } from '@/lib/api/facts';
import type { FactsView } from '@/lib/gen/rewind/v1/facts_pb';
import { Gate, VideoStatus, type Video } from '@/lib/gen/rewind/v1/video_pb';
import { material, palette } from '@/theme/tokens';

export function GateDecisionBar({ video, view }: { video: Video; view: FactsView }) {
  const router = useRouter();
  const { approve, reject } = useGateDecision(video.id);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState('');

  const canApprove = view.canApprove && video.awaitingGate === Gate.A_FACTS;

  return (
    <>
      {/* Sticky footer: the decision is always reachable without scrolling
          back, however long the fact list is. */}
      <Paper
        sx={{
          position: 'sticky',
          bottom: 16,
          p: 2.5,
          backgroundColor: palette.light.surface,
          backdropFilter: material.blur,
          WebkitBackdropFilter: material.blur,
        }}
      >
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          alignItems={{ xs: 'stretch', sm: 'center' }}
        >
          <Box sx={{ flex: 1 }}>
            <Typography variant="body1" sx={{ fontWeight: 600 }}>
              {view.approvedCount} approved across {view.eraCount} era
              {view.eraCount === 1 ? '' : 's'}
            </Typography>
            {!view.canApprove ? (
              <Typography variant="body2" color="text.secondary">
                {view.approvalBlocker}
              </Typography>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Ready to approve. The script will only ever use these facts.
              </Typography>
            )}
          </Box>

          <Stack direction="row" spacing={1.5}>
            <Button
              color="inherit"
              onClick={() => setRejecting(true)}
              disabled={video.awaitingGate !== Gate.A_FACTS}
            >
              Send back
            </Button>
            <Button
              variant="contained"
              disabled={!canApprove || approve.isPending}
              onClick={() =>
                approve.mutate(
                  { gate: Gate.A_FACTS, note: '' },
                  { onSuccess: () => router.push('/') },
                )
              }
            >
              {approve.isPending ? 'Approving…' : 'Approve Gate A'}
            </Button>
          </Stack>
        </Stack>

        {approve.isError ? (
          <Alert severity="error" sx={{ mt: 2 }}>
            {approve.error.message}
          </Alert>
        ) : null}
      </Paper>

      <Dialog open={rejecting} onClose={() => setRejecting(false)} fullWidth maxWidth="sm">
        <DialogTitle>Send this video back</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              The video returns to research, and the facts are gathered again. Say what was
              wrong — you will be reading this note when you pick it up.
            </Typography>
            <TextField
              autoFocus
              required
              label="What was wrong?"
              placeholder="The 1882 date contradicts the source it cites."
              value={note}
              onChange={(e) => setNote(e.target.value)}
              fullWidth
              multiline
              minRows={2}
            />
            {reject.isError ? <Alert severity="error">{reject.error.message}</Alert> : null}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 3 }}>
          <Button onClick={() => setRejecting(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="warning"
            disabled={!note.trim() || reject.isPending}
            onClick={() =>
              reject.mutate(
                {
                  gate: Gate.A_FACTS,
                  backTo: VideoStatus.RESEARCHING,
                  note: note.trim(),
                },
                {
                  onSuccess: () => {
                    setRejecting(false);
                    router.push('/');
                  },
                },
              )
            }
          >
            Send back to research
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

/**
 * GateCDecisionBar — approve the script, or send it back to be rewritten.
 *
 * Approve is enabled only when the API says so: no rule broken, and a title
 * chosen. The blocker is the worker's latest verdict, refreshed after every
 * edit, so the button never reflects a check that is out of date.
 *
 * "Send back" is also how to REGENERATE: the video returns to the script
 * step, which writes the script afresh from the same approved facts.
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
import type { ScriptView } from '@/lib/gen/rewind/v1/scripts_pb';
import { Gate, VideoStatus, type Video } from '@/lib/gen/rewind/v1/video_pb';
import { material } from '@/theme/tokens';

export function GateCDecisionBar({ video, view }: { video: Video; view: ScriptView }) {
  const router = useRouter();
  const { approve, reject } = useGateDecision(video.id);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState('');

  const beats = view.script?.beats.length ?? 0;

  return (
    <>
      <Paper
        sx={{
          position: 'sticky',
          bottom: 16,
          p: 2.5,
          backgroundColor: 'surface.translucent',
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
              {view.canApprove ? `${beats} beats, every rule met` : `${beats} beats`}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {view.canApprove
                ? 'Voice, images and captions will all be built from this script.'
                : view.approvalBlocker}
            </Typography>
          </Box>

          <Stack direction="row" spacing={1.5}>
            <Button color="inherit" onClick={() => setRejecting(true)}>
              Rewrite
            </Button>
            <Button
              variant="contained"
              disabled={!view.canApprove || approve.isPending}
              onClick={() =>
                approve.mutate({ gate: Gate.C_SCRIPT, note: '' }, { onSuccess: () => router.push('/') })
              }
            >
              {approve.isPending ? 'Approving…' : 'Approve Gate C'}
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
        <DialogTitle>Rewrite the script</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              The script is written again from the same approved facts and comparisons. Say what
              was wrong — you will read this when it comes back.
            </Typography>
            <TextField
              autoFocus
              required
              label="What was wrong?"
              placeholder="Too many jokes in a row; the rehook gives away the ending."
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
                { gate: Gate.C_SCRIPT, backTo: VideoStatus.REFS_APPROVED, note: note.trim() },
                {
                  onSuccess: () => {
                    setRejecting(false);
                    router.push('/');
                  },
                },
              )
            }
          >
            Rewrite
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

/**
 * GateBDecisionBar — approve Gate B, or send the video back.
 *
 * Note what does NOT block approval: choosing zero comparisons. A video with
 * no modern references is a straight history video, which is a legitimate
 * episode. SPEC.md 5.3 caps how many you may have; it never requires one.
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
import type { ReferencesView } from '@/lib/gen/rewind/v1/references_pb';
import { Gate, VideoStatus, type Video } from '@/lib/gen/rewind/v1/video_pb';
import { material } from '@/theme/tokens';

export function GateBDecisionBar({ video, view }: { video: Video; view: ReferencesView }) {
  const router = useRouter();
  const { approve, reject } = useGateDecision(video.id);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState('');

  const atGate = video.awaitingGate === Gate.B_REFERENCES;
  const canApprove = view.canApprove && atGate;

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
              {view.selectedCount} of {view.maxSelectable} comparisons chosen
            </Typography>
            {view.approvalBlocker ? (
              <Typography variant="body2" color="text.secondary">
                {view.approvalBlocker}
              </Typography>
            ) : view.selectedCount === 0 ? (
              <Typography variant="body2" color="text.secondary">
                None chosen — this will be a straight history video, which is fine.
              </Typography>
            ) : (
              <Typography variant="body2" color="text.secondary">
                The script will use only these, each tied to its fact.
              </Typography>
            )}
          </Box>

          <Stack direction="row" spacing={1.5}>
            <Button color="inherit" onClick={() => setRejecting(true)} disabled={!atGate}>
              Send back
            </Button>
            <Button
              variant="contained"
              disabled={!canApprove || approve.isPending}
              onClick={() =>
                approve.mutate(
                  { gate: Gate.B_REFERENCES, note: '' },
                  { onSuccess: () => router.push('/') },
                )
              }
            >
              {approve.isPending ? 'Approving…' : 'Approve Gate B'}
            </Button>
          </Stack>
        </Stack>

        {view.staleReferenceIds.length > 0 ? (
          <Alert severity="warning" sx={{ mt: 2 }}>
            {view.staleReferenceIds.length} chosen reference has passed its freshness date. You can
            still use it, but it will read as dated.
          </Alert>
        ) : null}

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
              The video returns to the reference step and the comparisons are written again. Say
              what was wrong — you will be reading this when you pick it up.
            </Typography>
            <TextField
              autoFocus
              required
              label="What was wrong?"
              placeholder="Every comparison is about footwear brands; needs more variety."
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
                  gate: Gate.B_REFERENCES,
                  backTo: VideoStatus.FACTS_APPROVED,
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
            Send back
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

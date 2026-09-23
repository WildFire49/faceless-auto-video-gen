/**
 * Reword a proposed comparison (SPEC.md 8.2).
 *
 * What this dialog deliberately does NOT offer: the reference itself, or its
 * kind. Those record where the comparison came from — the model's bank, a
 * trend, or you. Rewording the line is editing; swapping the brand underneath
 * it is a different comparison, and should be deleted and rewritten so the
 * review log stays honest about what was proposed and what was chosen.
 */

'use client';

import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useEffect, useState, type FormEvent } from 'react';

import type { ReferenceMutations } from '@/lib/api/references';
import type { Proposal } from '@/lib/gen/rewind/v1/relevance_pb';

export interface EditProposalDialogProps {
  /** null closes the dialog; the component renders nothing. */
  proposal: Proposal | null;
  onClose: () => void;
  mutations: ReferenceMutations;
}

export function EditProposalDialog({ proposal, onClose, mutations }: EditProposalDialogProps) {
  const [comparison, setComparison] = useState('');
  const [whyFunny, setWhyFunny] = useState('');

  // Re-seed whenever a different card is opened. Without this the dialog would
  // show the previous proposal's text for one frame.
  useEffect(() => {
    if (!proposal) return;
    setComparison(proposal.comparison);
    setWhyFunny(proposal.whyFunny);
    mutations.update.reset();
    // mutations is recreated each render; keying on the proposal is the intent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposal]);

  if (!proposal) return null;

  const close = () => {
    if (mutations.update.isPending) return;
    onClose();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutations.update.mutate(
      {
        proposalId: proposal.id,
        comparison: comparison.trim(),
        whyFunny: whyFunny.trim(),
        // Empty means "leave the linked fact alone" — the server treats it as
        // unchanged rather than as a request to unlink.
        linkedFactId: '',
      },
      { onSuccess: onClose },
    );
  };

  return (
    <Dialog
      open
      onClose={close}
      fullWidth
      maxWidth="sm"
      slotProps={{ paper: { component: 'form', onSubmit: submit } }}
    >
      <DialogTitle>Reword the {proposal.reference} line</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ pt: 1 }}>
          <TextField
            autoFocus
            required
            label="The line"
            helperText="One sentence, as the narrator will say it"
            value={comparison}
            onChange={(e) => setComparison(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />
          <TextField
            label="Why it works"
            helperText="For your own notes at the script gate"
            value={whyFunny}
            onChange={(e) => setWhyFunny(e.target.value)}
            fullWidth
          />
          <Typography variant="body2" color="text.secondary">
            Compare look, price, hype or behaviour. Never assert a fact about the brand — nothing
            here was researched, so there would be no source behind such a claim.
          </Typography>
          {mutations.update.isError ? (
            <Alert severity="error">{mutations.update.error.message}</Alert>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 3 }}>
        <Button onClick={close} disabled={mutations.update.isPending}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="contained"
          disabled={!comparison.trim() || mutations.update.isPending}
        >
          {mutations.update.isPending ? 'Saving…' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

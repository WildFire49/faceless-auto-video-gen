/**
 * Write your own comparison (SPEC.md 5.3, 8.2).
 *
 * A hand-written proposal skips the model's safety filter, because you are the
 * judgement those rules approximate. What it does NOT skip is the link to an
 * approved fact: a comparison exists to make one fact land, and an unattached
 * one has nothing to be funny about. The fact picker is therefore required and
 * lists only facts that survived Gate A.
 */

'use client';

import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useState, type FormEvent } from 'react';

import type { ReferenceMutations } from '@/lib/api/references';
import type { Fact } from '@/lib/gen/rewind/v1/research_pb';

export interface AddProposalDialogProps {
  open: boolean;
  onClose: () => void;
  /** The whole sheet; this component picks the approved ones itself. */
  facts: Fact[];
  mutations: ReferenceMutations;
}

export function AddProposalDialog({ open, onClose, facts, mutations }: AddProposalDialogProps) {
  const [reference, setReference] = useState('');
  const [comparison, setComparison] = useState('');
  const [whyFunny, setWhyFunny] = useState('');
  const [linkedFactId, setLinkedFactId] = useState('');

  const approved = facts.filter((fact) => fact.approved);

  const close = () => {
    if (mutations.add.isPending) return;
    setReference('');
    setComparison('');
    setWhyFunny('');
    setLinkedFactId('');
    mutations.add.reset();
    onClose();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutations.add.mutate(
      {
        reference: reference.trim(),
        comparison: comparison.trim(),
        whyFunny: whyFunny.trim(),
        linkedFactId,
      },
      { onSuccess: close },
    );
  };

  const ready = Boolean(reference.trim() && comparison.trim() && linkedFactId);

  return (
    <Dialog
      open={open}
      onClose={close}
      fullWidth
      maxWidth="sm"
      slotProps={{ paper: { component: 'form', onSubmit: submit } }}
    >
      <DialogTitle>Write your own comparison</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Yours is recorded as a manual proposal and counts against the same limit of three.
          </Typography>

          {approved.length === 0 ? (
            <Alert severity="warning">
              No approved facts to attach to. Approve facts at Gate A first.
            </Alert>
          ) : null}

          <TextField
            required
            autoFocus
            label="Modern thing"
            placeholder="Stanley cup"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            fullWidth
          />

          <TextField
            select
            required
            label="Attaches to"
            helperText="Which approved fact this is funny about"
            value={linkedFactId}
            onChange={(e) => setLinkedFactId(e.target.value)}
            fullWidth
            disabled={approved.length === 0}
          >
            {approved.map((fact) => (
              <MenuItem key={fact.id} value={fact.id}>
                {fact.label} — {fact.claim.slice(0, 70)}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            required
            label="The line"
            placeholder="It was the Stanley cup of ancient Egypt."
            value={comparison}
            onChange={(e) => setComparison(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />

          <TextField
            label="Why it works"
            value={whyFunny}
            onChange={(e) => setWhyFunny(e.target.value)}
            fullWidth
          />

          {mutations.add.isError ? (
            <Alert severity="error">{mutations.add.error.message}</Alert>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 3 }}>
        <Button onClick={close} disabled={mutations.add.isPending}>
          Cancel
        </Button>
        <Button type="submit" variant="contained" disabled={!ready || mutations.add.isPending}>
          {mutations.add.isPending ? 'Adding…' : 'Add it'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/**
 * AddFactDialog — add a fact you sourced yourself.
 *
 * Human-added facts skip the evidence verifier: a person citing a book is the
 * authority the verifier exists to substitute for. But a source URL is still
 * required, because SPEC.md 5.2 permits no unsourced claim anywhere in the
 * pipeline, however it got there.
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
import { useState } from 'react';

import type { useFactMutations } from '@/lib/api/facts';

type Mutations = ReturnType<typeof useFactMutations>;

export function AddFactDialog({
  open,
  onClose,
  mutations,
}: {
  open: boolean;
  onClose: () => void;
  mutations: Mutations;
}) {
  const [label, setLabel] = useState('');
  const [sortKey, setSortKey] = useState(0);
  const [factContext, setFactContext] = useState('');
  const [claim, setClaim] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [evidence, setEvidence] = useState('');

  const reset = () => {
    setLabel('');
    setSortKey(0);
    setFactContext('');
    setClaim('');
    setSourceUrl('');
    setEvidence('');
    mutations.addFact.reset();
  };

  const close = () => {
    if (mutations.addFact.isPending) return;
    reset();
    onClose();
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    mutations.addFact.mutate(
      {
        label: label.trim(),
        sortKey,
        context: factContext.trim(),
        claim: claim.trim(),
        sourceUrl: sourceUrl.trim(),
        evidence: evidence.trim(),
      },
      { onSuccess: close },
    );
  };

  const ready = claim.trim() && label.trim() && sourceUrl.trim();

  return (
    <Dialog
      open={open}
      onClose={close}
      fullWidth
      maxWidth="sm"
      slotProps={{ paper: { component: 'form', onSubmit: submit } }}
    >
      <DialogTitle>Add a fact</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            A fact you found yourself. It is approved on arrival — typing it in is the
            approval — but it still needs a source, like every other fact in the pipeline.
          </Typography>

          <Stack direction="row" spacing={2}>
            <TextField
              required
              autoFocus
              label="Label"
              placeholder="1882"
              helperText="What the narrator says first"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              fullWidth
            />
            <TextField
              required
              type="number"
              label="Sort key"
              helperText="Orders the items"
              value={sortKey}
              onChange={(e) => setSortKey(Number(e.target.value))}
              fullWidth
            />
          </Stack>

          <TextField
            label="Context"
            placeholder="New York, USA"
            value={factContext}
            onChange={(e) => setFactContext(e.target.value)}
            fullWidth
          />

          <TextField
            required
            label="Claim"
            placeholder="Henry Seely patented the first electric iron."
            value={claim}
            onChange={(e) => setClaim(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />

          <TextField
            required
            label="Source URL"
            placeholder="https://..."
            helperText="Where you found it. Required — no unsourced facts."
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            fullWidth
          />

          <TextField
            label="Supporting quote"
            helperText="Optional, but it is what you will check against later."
            value={evidence}
            onChange={(e) => setEvidence(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />

          {mutations.addFact.isError ? (
            <Alert severity="error">{mutations.addFact.error.message}</Alert>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 3 }}>
        <Button onClick={close} disabled={mutations.addFact.isPending}>
          Cancel
        </Button>
        <Button type="submit" variant="contained" disabled={!ready || mutations.addFact.isPending}>
          {mutations.addFact.isPending ? 'Adding…' : 'Add fact'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

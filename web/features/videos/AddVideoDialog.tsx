/**
 * AddVideoDialog — queue a new topic.
 *
 * The same operation as `rewind add`, through the same service layer.
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
import { useState } from 'react';

import { useAddVideo } from '@/lib/api/videos';

const PRIORITIES = [
  { value: 1, label: '1 — do this next' },
  { value: 2, label: '2 — soon' },
  { value: 3, label: '3 — normal' },
  { value: 4, label: '4 — whenever' },
  { value: 5, label: '5 — someday' },
];

export function AddVideoDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [topic, setTopic] = useState('');
  const [priority, setPriority] = useState(3);
  const [notes, setNotes] = useState('');

  const addVideo = useAddVideo();

  function handleClose() {
    if (addVideo.isPending) return; // don't drop a request mid-flight
    addVideo.reset();
    setTopic('');
    setNotes('');
    setPriority(3);
    onClose();
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = topic.trim();
    if (!trimmed) return;

    addVideo.mutate(
      { topic: trimmed, priority, notes: notes.trim() },
      { onSuccess: handleClose },
    );
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      fullWidth
      maxWidth="sm"
      slotProps={{ paper: { component: 'form', onSubmit: handleSubmit } }}
    >
      <DialogTitle>Queue a topic</DialogTitle>

      <DialogContent>
        <Stack spacing={3} sx={{ pt: 1 }}>
          <TextField
            autoFocus
            required
            label="Topic"
            placeholder="computer mouse"
            helperText="An everyday object. The episode traces it from its oldest version to today."
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            fullWidth
          />

          <TextField
            select
            label="Priority"
            value={priority}
            onChange={(e) => setPriority(Number(e.target.value))}
            fullWidth
          >
            {PRIORITIES.map((p) => (
              <MenuItem key={p.value} value={p.value}>
                {p.label}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            label="Notes"
            placeholder="compare to Birkenstocks, Crocs"
            helperText="Optional. Notes for yourself, and hints for the research step."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />

          {addVideo.isError ? (
            <Alert severity="error">{addVideo.error.message}</Alert>
          ) : null}
        </Stack>
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 3 }}>
        <Button onClick={handleClose} disabled={addVideo.isPending}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="contained"
          disabled={!topic.trim() || addVideo.isPending}
        >
          {addVideo.isPending ? 'Queueing…' : 'Queue it'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

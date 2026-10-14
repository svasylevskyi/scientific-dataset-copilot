import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Alert, Button, CircularProgress, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material';
import { request, type AnalysisInput, type SavedAnalysis, type PlannerStatus, type PlanningView, type Proposal } from './api';

const errorText = (error: unknown) => error instanceof Error ? error.message : 'Please try again.';

export function Copilot({ userId, onManual, onSaved }: {
  userId: string; onManual: () => void; onSaved: (analysis: SavedAnalysis) => Promise<void>;
}) {
  const storageKey = `sdc-planning-${userId}`;
  const [status, setStatus] = useState<PlannerStatus | null>(null);
  const [plan, setPlan] = useState<PlanningView | null>(null);
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [recoverId, setRecoverId] = useState<string | null>(() => localStorage.getItem(storageKey));
  const pending = useRef<{ request_key: string; prompt: string; parent_id: string | null } | null>(null);
  const clarification = plan?.status === 'clarification' && plan.turn < 3;

  async function loadStatus() { setStatus(await request<PlannerStatus>('copilot/status')); }
  useEffect(() => {
    let disposed = false;
    request<PlannerStatus>('copilot/status').then(value => { if (!disposed) setStatus(value); })
      .catch(e => { if (!disposed) setError(errorText(e)); });
    const key = localStorage.getItem(storageKey);
    if (key) request<PlanningView>(`copilot/requests/${key}`).then(value => {
      if (!disposed) { setPlan(value); setRecoverId(null); }
    }).catch(e => { if (!disposed) setError(errorText(e)); });
    return () => { disposed = true; };
  }, [storageKey]);

  async function refresh() {
    const key = recoverId ?? plan?.id;
    if (!key) return;
    setBusy(true); setError('');
    try { setPlan(await request<PlanningView>(`copilot/requests/${key}`)); setRecoverId(null); await loadStatus(); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    const parent = clarification ? plan!.id : null;
    if (!pending.current || pending.current.prompt !== prompt || pending.current.parent_id !== parent) {
      pending.current = { request_key: crypto.randomUUID(), prompt, parent_id: parent };
    }
    const body = pending.current;
    // Retain only the ID in browser storage; the owner-scoped API holds the private proposal.
    localStorage.setItem(storageKey, body.request_key);
    setRecoverId(body.request_key);
    try {
      const value = await request<PlanningView>('copilot/requests', body, undefined, 30000);
      setPlan(value); setRecoverId(null); setPrompt(''); pending.current = null;
      await loadStatus();
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  function reset() {
    setPlan(null); setRecoverId(null); setPrompt(''); setError(''); pending.current = null;
    localStorage.removeItem(storageKey);
  }
  return <Paper className="panel" component="section" aria-label="Guided planning">
    <Typography variant="h5" component="h2">Describe your analysis</Typography>
    <Typography color="text.secondary" sx={{ my: 1 }}>Ask for monthly sea surface temperature around the Canary Islands or Madeira. You will review the proposal before saving or running it.</Typography>
    {status?.blocked_reason && <Alert severity="info" sx={{ my: 2 }}>{status.blocked_reason}</Alert>}
    {error && <Alert severity="error" sx={{ my: 2 }}>{error} You can keep using the manual form.</Alert>}
    {status?.enabled && <Typography variant="body2" sx={{ mb: 2 }}>{status.remaining} of {status.daily_limit} planning requests remaining today · resets at 00:00 UTC. Planning uses no analysis allowance.</Typography>}
    {plan && <>
      <Typography variant="body2" sx={{ mt: 2, overflowWrap: 'anywhere' }}>Your request: {plan.prompt}</Typography>
      <Alert severity={plan.status === 'ready' ? 'success' : plan.status === 'failed' ? 'warning' : 'info'} sx={{ my: 2 }}>{plan.message}</Alert>
    </>}
    {(!plan || clarification) && <form onSubmit={submit}><Stack gap={2}>
      <TextField label={clarification ? 'Your clarification' : 'What would you like to analyse?'} multiline minRows={2} required
        value={prompt} onChange={e => setPrompt(e.target.value)} disabled={busy || !status?.enabled || Boolean(status.blocked_reason)}
        slotProps={{ htmlInput: { minLength: 3, maxLength: 2000 } }} helperText={`${prompt.length}/2000 characters`} />
      {!clarification && <Button sx={{ alignSelf: 'flex-start', textAlign: 'left' }} disabled={busy || !status?.enabled}
        onClick={() => setPrompt('Show monthly sea surface temperature around Madeira during 2023.')}>Try an example</Button>}
      <Typography variant="body2" color="text.secondary">Your request and clarifications are sent to OpenAI to prepare the proposal. Do not include personal or confidential information.</Typography>
      <Button type="submit" variant="contained" sx={{ alignSelf: 'flex-start' }} disabled={busy || !status?.enabled || Boolean(status.blocked_reason) || prompt.trim().length < 3}>
        {busy ? 'Preparing…' : clarification ? 'Send clarification' : 'Prepare proposal'}
      </Button>
    </Stack></form>}
    {busy && <CircularProgress size={24} aria-label="Preparing proposal" sx={{ mt: 2 }} />}
    {(recoverId || plan?.status === 'pending') && <Button onClick={refresh} disabled={busy}>Check request status</Button>}
    {plan?.status === 'clarification' && !clarification && <Typography>We still need more detail. Start a new request or use the manual form.</Typography>}
    {plan?.status === 'ready' && plan.proposal && !plan.analysis_id && <ProposalEditor key={plan.id} initial={plan.proposal} id={plan.id} onSaved={async saved => {
      setPlan({ ...plan, analysis_id: saved.id }); await onSaved(saved);
    }} />}
    {plan?.analysis_id && <Alert severity="success" sx={{ mt: 2 }}>Proposal saved. <Button href={`#/analyses?id=${plan.analysis_id}`}>Open saved analysis</Button> Use Run analysis when you are ready.</Alert>}
    <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: 2 }}>
      <Button onClick={onManual} disabled={busy}>Use manual form</Button>
      {(plan || recoverId) && <Button onClick={reset} disabled={busy || plan?.status === 'pending'}>New request</Button>}
    </Stack>
  </Paper>;
}

function ProposalEditor({ initial, id, onSaved }: { initial: Proposal; id: string; onSaved: (value: SavedAnalysis) => Promise<void> }) {
  const [draft, setDraft] = useState<AnalysisInput>(initial.analysis);
  const [checked, setChecked] = useState<Proposal | null>(initial);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  function edit(value: AnalysisInput) { setDraft(value); setChecked(null); setError(''); }
  async function validate(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { setChecked(await request<Proposal>('copilot/preview', draft)); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setError('');
    try { await onSaved(await request<SavedAnalysis>(`copilot/requests/${id}/accept`, draft)); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  return <section aria-label="Review proposal">
    <Typography variant="h6" component="h3" sx={{ my: 2 }}>Review your proposal</Typography>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    <form onSubmit={validate}><Stack gap={2}>
      <TextField label="Proposal title" required value={draft.title} disabled={busy} slotProps={{ htmlInput: { maxLength: 120 } }} onChange={e => edit({ ...draft, title: e.target.value })} />
      <div className="form-grid">
        <TextField label="Proposal region" select value={draft.query.region_id} disabled={busy} onChange={e => edit({ ...draft, query: { ...draft.query, region_id: e.target.value as 'canaries' | 'madeira' } })}>
          <MenuItem value="canaries">Canary Islands — surrounding ocean</MenuItem><MenuItem value="madeira">Madeira — surrounding ocean</MenuItem>
        </TextField>
        <TextField label="Proposal from" type="date" required value={draft.query.start} disabled={busy} slotProps={{ inputLabel: { shrink: true } }} onChange={e => edit({ ...draft, query: { ...draft.query, start: e.target.value } })} />
        <TextField label="Proposal to" type="date" required value={draft.query.end} disabled={busy} slotProps={{ inputLabel: { shrink: true } }} onChange={e => edit({ ...draft, query: { ...draft.query, end: e.target.value } })} />
      </div>
      {!checked && <><Typography>Validate your edits to refresh the proposal before saving.</Typography><Button type="submit" disabled={busy} variant="outlined">Validate edits</Button></>}
    </Stack></form>
    {checked && <>
      <Typography sx={{ mt: 2 }}><strong>Source:</strong> NOAA OISST v2.1 · Sea surface temperature · °C</Typography>
      <Typography><strong>Method:</strong> {checked.method}</Typography>
      <Typography><strong>Region:</strong> {checked.plan.region.name} ({checked.plan.region.bounds.south}–{checked.plan.region.bounds.north}° N, {checked.plan.region.bounds.west}–{checked.plan.region.bounds.east}° longitude).</Typography>
      <Typography><strong>Dates:</strong> {checked.analysis.query.start} to {checked.analysis.query.end}, inclusive UTC days.</Typography>
      <Typography variant="body2" sx={{ mt: 1 }}>Source metadata checked {new Date(checked.plan.metadata_fetched_at).toLocaleDateString('en-GB', { timeZone: 'UTC' })}; recorded coverage {checked.plan.source.coverage_start} to {checked.plan.source.coverage_end}. Current coverage is checked again during execution.</Typography>
      <ul>{checked.plan.warnings.map(warning => <li key={warning}>{warning}</li>)}<li>Monthly values with insufficient coverage are withheld. This workflow does not calculate trends, anomalies or causes.</li></ul>
      <Typography>Saving uses no allowance. Starting this analysis reserves {checked.allowance_required} analysis; successful results are retained for {checked.retention_days} days under your current plan.</Typography>
      {checked.blocked_reason && <Alert severity="warning" sx={{ my: 2 }}>{checked.blocked_reason} You can save this proposal for later.</Alert>}
      <Button variant="contained" onClick={save} disabled={busy} sx={{ mt: 2 }}>Confirm and save analysis</Button>
    </>}
  </section>;
}

import { lazy, Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import {
  Alert, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent,
  DialogContentText, DialogTitle, MenuItem, Paper, Stack, TextField, Typography,
} from '@mui/material';
import { useAccount, useRoute } from './Account';
import { Copilot } from './Copilot';
import { request, type Analysis, type AnalysisInput, type AnalysisRun, type RunDetail, type SavedAnalysis, type Usage } from './api';

const Chart = lazy(() => import('./Chart'));
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Please try again.';
const stamp = (value: string) => new Date(value).toLocaleString('en-GB', { timeZone: 'UTC' }) + ' UTC';
const href = (id: string, run?: string) => `#/analyses?id=${id}${run ? `&run=${run}` : ''}`;
const active = (run: AnalysisRun) => ['queued', 'running'].includes(run.status);

export function AnalysesScreen() {
  const { user, loading } = useAccount();
  if (loading) return <CircularProgress aria-label="Loading account" />;
  if (!user) return <Paper className="panel"><Typography variant="h4" component="h1">Your analyses</Typography>
    <p>Sign in to save ocean-data queries and run analyses with your plan allowance.</p><Button href="#/signin" variant="contained">Sign in</Button></Paper>;
  return <AnalysisWorkspace key={user.id} />;
}

function Editor({ analysis, onSave, onClose }: { analysis: SavedAnalysis | null; onSave: (value: SavedAnalysis) => Promise<void>; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const data = new FormData(event.currentTarget);
    const body: AnalysisInput = { title: String(data.get('title')), query: {
      region_id: String(data.get('region')) as 'canaries' | 'madeira', start: String(data.get('start')), end: String(data.get('end')),
    } };
    try {
      const result = await request<SavedAnalysis>(analysis ? `analyses/${analysis.id}` : 'analyses',
        analysis ? { ...body, version: analysis.version } : body, analysis ? 'PATCH' : 'POST');
      await onSave(result);
    } catch (error) { setError(errorText(error)); }
    finally { setBusy(false); }
  }
  return <Paper className="panel">
    <Typography variant="h6" component="h2" sx={{ mb: 2 }}>{analysis ? 'Edit analysis' : 'New analysis'}</Typography>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    <form onSubmit={submit}><Stack gap={2}>
      <TextField name="title" label="Analysis title" required defaultValue={analysis?.title ?? ''} slotProps={{ htmlInput: { maxLength: 120 } }} disabled={busy} />
      <div className="form-grid">
        <TextField name="region" label="Region" select defaultValue={analysis?.query.region_id ?? 'canaries'} disabled={busy}>
          <MenuItem value="canaries">Canary Islands — surrounding ocean</MenuItem><MenuItem value="madeira">Madeira — surrounding ocean</MenuItem>
        </TextField>
        <TextField name="start" label="From" type="date" required defaultValue={analysis?.query.start ?? '2020-01-01'} slotProps={{ inputLabel: { shrink: true } }} disabled={busy} />
        <TextField name="end" label="To" type="date" required defaultValue={analysis?.query.end ?? '2020-12-31'} slotProps={{ inputLabel: { shrink: true } }} disabled={busy} />
      </div>
      <Typography variant="body2" color="text.secondary">NOAA OISST v2.1 · Sea surface temperature in °C · Area-weighted monthly means. Dates are checked against current source coverage when a run starts. Saving is free; each successful run uses one analysis. Editing keeps all previous run snapshots.</Typography>
      <Stack direction="row" gap={1}><Button type="submit" variant="contained" disabled={busy}>{busy ? 'Saving…' : 'Save analysis'}</Button><Button onClick={onClose} disabled={busy}>Cancel</Button></Stack>
    </Stack></form>
  </Paper>;
}

function AnalysisWorkspace() {
  const { user } = useAccount();
  const { hash } = useRoute();
  const params = new URLSearchParams(hash.split('?')[1]);
  const selectedId = params.get('id'); const runId = params.get('run');
  const [analyses, setAnalyses] = useState<SavedAnalysis[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const [editor, setEditor] = useState<SavedAnalysis | null | undefined>();
  const [confirm, setConfirm] = useState(false); const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const pending = useRef<{ analysisId: string; version: number; key: string } | null>(null);
  const selected = analyses.find(a => a.id === selectedId);
  const load = useCallback(async () => {
    setError('');
    try {
      const [items, allowance] = await Promise.all([request<SavedAnalysis[]>('analyses'), request<Usage>('account/usage')]);
      setAnalyses(items); setUsage(allowance);
    } catch (error) { setError(errorText(error)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load, revision]);
  useEffect(() => { setEditor(undefined); setConfirm(false); }, [selectedId]);
  async function start() {
    if (!selected) return;
    setBusy(true); setError('');
    if (pending.current?.analysisId !== selected.id || pending.current?.version !== selected.version) {
      pending.current = { analysisId: selected.id, version: selected.version, key: crypto.randomUUID() };
    }
    try {
      const run = await request<RunDetail>(`analyses/${selected.id}/runs`, { run_key: pending.current.key, version: selected.version });
      pending.current = null; setConfirm(false); window.location.hash = href(selected.id, run.id).slice(1); setRevision(r => r + 1);
    } catch (error) { setError(errorText(error)); setConfirm(false); }
    finally { setBusy(false); }
  }
  return <>
    <div className="title-row"><div><div className="eyebrow">YOUR WORKSPACE</div><Typography variant="h4" component="h1" fontWeight={650}>Your analyses</Typography></div>
      <Stack direction="row" gap={1}><Button onClick={() => setEditor(null)} variant="contained">New analysis</Button><Button onClick={() => setRevision(r => r + 1)}>Refresh</Button></Stack></div>
    <Typography color="text.secondary" sx={{ my: 2 }}>Save a query, run it against NOAA, and return to its results at any time during retention.</Typography>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    {usage && <Alert severity={usage.blocked_reason ? 'warning' : 'info'} sx={{ mb: 3 }} action={<Button color="inherit" href="#/usage">Usage</Button>}>
      {usage.remaining} analyses remaining this month · {usage.concurrent_reserved}/{usage.plan.concurrent_analyses} simultaneous slots reserved. {usage.blocked_reason ?? `New results are kept for ${usage.plan.retention_days} days.`}
    </Alert>}
    <Copilot userId={user!.id} onManual={() => setEditor(null)} onSaved={async value => {
      setEditor(undefined); await load(); window.location.hash = href(value.id).slice(1); setRevision(r => r + 1);
    }} />
    {editor !== undefined && <Editor key={editor?.id ?? 'new'} analysis={editor} onClose={() => setEditor(undefined)} onSave={async value => {
      setEditor(undefined); await load(); window.location.hash = href(value.id).slice(1); setRevision(r => r + 1);
    }} />}
    {loading ? <CircularProgress aria-label="Loading analyses" /> : !analyses.length ? <Paper className="panel"><Typography>No saved analyses yet. Create your first ocean-data query.</Typography></Paper> :
      <div className="analysis-tabs" aria-label="Saved analyses">{analyses.map(item => <Button key={item.id} href={href(item.id)} variant={item.id === selectedId ? 'contained' : 'outlined'}>{item.title}</Button>)}</div>}
    {selectedId && !loading && !selected && <Alert severity="warning">Analysis not found in your workspace.</Alert>}
    {selected && <>
      <Paper className="panel"><div className="title-row"><div><Typography variant="h5" component="h2">{selected.title}</Typography>
        <Typography color="text.secondary">{selected.query.region_id === 'canaries' ? 'Canary Islands' : 'Madeira'} · {selected.query.start} to {selected.query.end}</Typography></div>
        <Stack direction="row" gap={1}><Button onClick={() => setEditor(selected)}>Edit query</Button><Button variant="contained" disabled={busy || !usage?.can_reserve} onClick={() => setConfirm(true)}>Run analysis</Button></Stack></div>
        <Typography variant="body2" sx={{ mt: 2 }}>Runs continue if you close the browser. Failed or cancelled runs release their allowance reservation. Automatic recovery retries keep the same reservation; starting another run creates a new one.</Typography>
      </Paper>
      <RunHistory key={`${selected.id}-${revision}`} analysisId={selected.id} selectedRun={runId} />
      {runId && <RunPanel key={runId} runId={runId} onChanged={() => setRevision(r => r + 1)} />}
    </>}
    <Dialog open={confirm} onClose={() => { if (!busy) setConfirm(false); }} aria-labelledby="run-confirm-title">
      <DialogTitle id="run-confirm-title">Start this analysis?</DialogTitle><DialogContent><DialogContentText>
        Download NOAA data for {selected?.query.start} to {selected?.query.end}. This reserves one analysis from your allowance. You can cancel a queued or running analysis.
      </DialogContentText></DialogContent><DialogActions><Button disabled={busy} onClick={() => setConfirm(false)}>Back</Button><Button disabled={busy} onClick={start}>{busy ? 'Starting…' : 'Start run'}</Button></DialogActions>
    </Dialog>
  </>;
}

function RunHistory({ analysisId, selectedRun }: { analysisId: string; selectedRun: string | null }) {
  const [runs, setRuns] = useState<AnalysisRun[]>([]); const [offset, setOffset] = useState(0); const [error, setError] = useState('');
  useEffect(() => { let disposed = false;
    request<AnalysisRun[]>(`analyses/${analysisId}/runs?offset=${offset}`).then(value => { if (!disposed) setRuns(value); }).catch(e => { if (!disposed) setError(errorText(e)); });
    return () => { disposed = true; };
  }, [analysisId, offset]);
  return <Paper className="panel"><Typography variant="h6" component="h2">Run history</Typography>
    {error && <Alert severity="error">{error}</Alert>}
    {!runs.length && <Typography sx={{ mt: 1 }}>No runs on this page.</Typography>}
    {runs.map(run => <div className="session-row" key={run.id}><div><Typography>{stamp(run.created_at)}</Typography><Typography variant="body2" color="text.secondary">{run.query.start} to {run.query.end} · {run.status}{run.status === 'succeeded' && !run.results_available ? ' · Results expired' : ''}</Typography></div>
      <Button href={href(analysisId, run.id)} variant={run.id === selectedRun ? 'outlined' : 'text'}>View run</Button></div>)}
    <Stack direction="row" gap={1}><Button disabled={offset === 0} onClick={() => setOffset(n => Math.max(0, n - 25))}>Newer runs</Button><Button disabled={runs.length < 25} onClick={() => setOffset(n => n + 25)}>Older runs</Button></Stack>
  </Paper>;
}

function RunPanel({ runId, onChanged }: { runId: string; onChanged: () => void }) {
  const [run, setRun] = useState<RunDetail | null>(null); const [result, setResult] = useState<Analysis | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [confirm, setConfirm] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let disposed = false; let timer: number | undefined; let lastStatus = '';
    async function poll() {
      try {
        const current = await request<RunDetail>(`runs/${runId}`);
        if (disposed) return;
        setRun(current); setError('');
        if (lastStatus && lastStatus !== current.status) onChanged();
        lastStatus = current.status;
        if (active(current)) timer = window.setTimeout(poll, 2000);
        else if (current.results_available) {
          const value = await request<Analysis>(`runs/${runId}/result`); if (!disposed) setResult(value);
        }
      } catch (error) { if (!disposed) setError(errorText(error)); }
    }
    void poll(); return () => { disposed = true; window.clearTimeout(timer); };
  }, [runId, reload]);
  async function cancel() {
    setBusy(true); setError('');
    try { setRun(await request<RunDetail>(`runs/${runId}/cancel`, {})); setConfirm(false); setReload(n => n + 1); onChanged(); }
    catch (error) { setError(errorText(error)); }
    finally { setBusy(false); }
  }
  const artifactHref = (id: string) => `/api/v1/runs/${runId}/artifacts/${id}`;
  return <>
    <Paper className="panel" component="section" aria-label="Selected run">
      <div className="title-row"><Typography variant="h6" component="h2">Run details</Typography><Button onClick={() => setReload(n => n + 1)}>Refresh run</Button></div>
      {error && <Alert severity="error" sx={{ my: 2 }}>{error}</Alert>}
      {!run && !error && <CircularProgress aria-label="Loading run" />}
      {run && <>
        <Stack direction="row" gap={1} flexWrap="wrap" sx={{ my: 2 }}><Chip label={run.status} color={run.status === 'succeeded' ? 'success' : run.status === 'failed' ? 'error' : 'default'} /><Chip variant="outlined" label={`Attempt ${run.attempt} / 3`} /></Stack>
        <Typography>{run.title} · {run.query.start} to {run.query.end}</Typography>
        {active(run) && <Alert severity="info" sx={{ my: 2 }}>{run.cancel_requested_at ? 'Waiting for the worker to confirm cancellation.' : run.status === 'queued' ? 'Waiting for a worker. You can leave this page and return later.' : 'Processing your query. Recovery after an interrupted worker may take up to 11 minutes.'}</Alert>}
        {run.error && <Alert severity="error" sx={{ my: 2 }}>{run.error}</Alert>}
        {run.status === 'succeeded' && <Typography sx={{ my: 2 }}>{run.results_available ? `Results available until ${stamp(run.expires_at!)}.` : 'Results have expired. Run history and usage records are retained.'}</Typography>}
        {active(run) && <Button color="warning" variant="outlined" disabled={busy || !!run.cancel_requested_at} onClick={() => setConfirm(true)}>Cancel run</Button>}
        <details className="run-stages" open><summary>Processing history</summary><ol>{run.events.map(event => <li key={event.id}><strong>{event.message}</strong><br /><small>{stamp(event.created_at)} · Attempt {event.attempt}</small></li>)}</ol></details>
      </>}
    </Paper>
    {result && run?.results_available && <>
      <Paper className="panel chart-panel"><Typography variant="h6" component="h2">Monthly sea surface temperature</Typography>
        <Typography color="text.secondary">{result.plan.region.name} · {result.received_days}/{result.expected_days} requested days received · {result.eligible_cells} eligible cells</Typography>
        <Suspense fallback={<CircularProgress aria-label="Loading chart" />}><Chart analysis={result} /></Suspense>
        <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: 2 }}>{run.artifacts.filter(a => ['monthly.csv', 'analysis.json'].includes(a.name)).map(a => <Button key={a.id} href={artifactHref(a.id)} variant="contained">{a.name === 'monthly.csv' ? 'Download CSV' : 'Download provenance'}</Button>)}</Stack>
      </Paper>
      <Paper className="panel"><Typography variant="h6" component="h2">Coverage and limitations</Typography><ul>{result.warnings.map(w => <li key={w}>{w}</li>)}</ul>
        <details><summary>Source data and reproducibility files</summary><ul>{run.artifacts.map(a => <li key={a.id}><a href={artifactHref(a.id)}>{a.name}</a> · {(a.bytes / 1024).toFixed(1)} KB<code className="artifact-hash">SHA-256: {a.sha256}</code></li>)}</ul></details>
      </Paper>
    </>}
    <Dialog open={confirm} onClose={() => { if (!busy) setConfirm(false); }} aria-labelledby="cancel-run-title"><DialogTitle id="cancel-run-title">Cancel this run?</DialogTitle><DialogContent><DialogContentText>The allowance is released once execution has stopped. A result that finishes before cancellation is accepted may already be completed.</DialogContentText></DialogContent><DialogActions><Button onClick={() => setConfirm(false)} disabled={busy}>Keep running</Button><Button onClick={cancel} disabled={busy}>Confirm cancellation</Button></DialogActions></Dialog>
  </>;
}

import { lazy, Suspense, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Alert, Box, Button, Chip, CircularProgress, CssBaseline, MenuItem, Paper,
  TextField, ThemeProvider, Typography, createTheme,
} from '@mui/material';
import { request, type Analysis, type AnalysisRequest, type QueryPlan } from './api';
import './style.css';

const Chart = lazy(() => import('./Chart'));
const theme = createTheme({
  palette: { primary: { main: '#14695f' }, background: { default: '#f4f7f5' }, text: { primary: '#193b3e', secondary: '#596e70' } },
  shape: { borderRadius: 12 },
  typography: { fontFamily: 'Inter, system-ui, -apple-system, sans-serif', button: { textTransform: 'none', fontWeight: 650 } },
  components: { MuiButton: { defaultProps: { disableElevation: true } }, MuiPaper: { defaultProps: { elevation: 0 } } },
});

function Planner({ analysis }: { analysis: Analysis }) {
  const [form, setForm] = useState<AnalysisRequest>({ region_id: 'canaries', start: '2016-01-01', end: '2025-12-31' });
  const [plan, setPlan] = useState<QueryPlan | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  function change(update: Partial<AnalysisRequest>) { setForm({ ...form, ...update }); setPlan(null); setError(''); }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setLoading(true); setError(''); setPlan(null);
    try { setPlan(await request<QueryPlan>('query-preview', form)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Query preview failed.'); }
    finally { setLoading(false); }
  }
  return <>
    <Typography variant="h4" component="h1" fontWeight={650}>Plan an ocean-data query</Typography>
    <Typography color="text.secondary" sx={{ mt: 1, mb: 3 }}>Choose a region and dates to inspect the data request before downloading.</Typography>
    <Paper className="panel">
      <Alert severity="info" sx={{ mb: 3 }}>This preview builds a query using saved source metadata. It does not download new data or change the reference chart.</Alert>
      <form onSubmit={submit}>
        <div className="form-grid">
          <TextField select label="Region" value={form.region_id} disabled={loading} onChange={e => change({ region_id: e.target.value as AnalysisRequest['region_id'] })}>
            <MenuItem value="canaries">Canary Islands — surrounding ocean</MenuItem>
            <MenuItem value="madeira">Madeira — surrounding ocean</MenuItem>
          </TextField>
          <TextField label="From" type="date" required disabled={loading} value={form.start} onChange={e => change({ start: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} />
          <TextField label="To" type="date" required disabled={loading} value={form.end} onChange={e => change({ end: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} />
        </div>
        <Typography variant="body2" color="text.secondary" sx={{ my: 2 }}>Snapshot coverage: {analysis.plan.source.coverage_start} to {analysis.plan.source.coverage_end}. Maximum interval: ten years.</Typography>
        <Button variant="contained" type="submit" disabled={loading}>{loading ? 'Preparing…' : 'Preview query'}</Button>
      </form>
      {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
    </Paper>
    {plan && <Paper className="panel" aria-live="polite">
      <Typography variant="h6">Your query plan</Typography>
      <p>{plan.region.name} · {plan.request.start} to {plan.request.end}</p>
      <p>{plan.estimated_cells.toLocaleString()} estimated cell-time values in {plan.chunks.length} bounded requests.</p>
      <p>Selected grid centers: {plan.selected_grid_bounds.south}° to {plan.selected_grid_bounds.north}° latitude; {plan.selected_grid_bounds.west}° to {plan.selected_grid_bounds.east}° longitude.</p>
      <ul>{plan.warnings.map(w => <li key={w}>{w}</li>)}</ul>
      <details><summary>Inspect generated ERDDAP URLs</summary>{plan.chunks.map(c => <div className="query" key={c.start}><strong>{c.start} → {c.end}</strong><code>{c.url}</code></div>)}</details>
    </Paper>}
  </>;
}

function Reference({ analysis }: { analysis: Analysis }) {
  const withheld = analysis.months.filter(m => m.mean_celsius === null).length;
  return <>
    <div className="title-row">
      <div><div className="eyebrow">OCEAN / CLIMATE · REFERENCE ANALYSIS</div><Typography variant="h4" component="h1" fontWeight={650}>A decade around the Canaries</Typography><Typography color="text.secondary" sx={{ mt: 1 }}>Monthly sea surface temperature · January 2016 – December 2025</Typography></div>
      <Chip label="NOAA OISST v2.1" variant="outlined" />
    </div>
    <div className="stats">
      <Paper className="stat"><span>Analysis period</span><strong>10 years</strong><small>{analysis.months.length} monthly values{withheld ? ` · ${withheld} withheld` : ''}</small></Paper>
      <Paper className="stat"><span>Spatial resolution</span><strong>0.25°</strong><small>{analysis.eligible_cells} eligible grid cells</small></Paper>
      <Paper className="stat"><span>Daily coverage</span><strong>{(100 * analysis.received_days / analysis.expected_days).toFixed(1)}%</strong><small>{analysis.received_days.toLocaleString()} of {analysis.expected_days.toLocaleString()} requested days</small></Paper>
    </div>
    <Paper className="panel chart-panel">
      <div className="title-row"><div><Typography variant="h6">Sea surface temperature</Typography><Typography variant="body2" color="text.secondary">Area-weighted daily means, aggregated by month</Typography></div><Button variant="contained" href="/api/v1/reference.csv">Download CSV</Button></div>
      <Suspense fallback={<Box sx={{ height: 430, display: 'grid', placeItems: 'center' }}><CircularProgress aria-label="Loading chart" /></Box>}><Chart analysis={analysis} /></Suspense>
    </Paper>
    <div className="detail-grid">
      <Paper className="panel"><div className="eyebrow">TRANSPARENT METHODS</div><Typography variant="h6">What this chart represents</Typography><p>Mean ocean surface temperature within 27–30° N and 19–13° W. Cells are weighted by area before daily values are averaged into calendar months.</p><p>This is a gridded, blended analysis. It does not describe the water at a particular beach, and the seasonal pattern alone does not establish a climate trend.</p><a href={analysis.plan.source.citation_url} target="_blank" rel="noreferrer">Read the dataset documentation ↗</a></Paper>
      <Paper className="panel"><div className="eyebrow">SOURCE & REPRODUCIBILITY</div><Typography variant="h6">Every result has a record</Typography><p>Retrieved {new Date(analysis.created_at).toLocaleDateString('en-GB', { timeZone: 'UTC' })}. The displayed example is a saved result, not a live feed.</p><p>Source identifiers, query URLs, checksums, software versions, and coverage checks accompany the data.</p><Button variant="outlined" href="/api/v1/reference.json">Download provenance</Button></Paper>
    </div>
    <Paper className="panel"><details><summary>Limitations and coverage notes</summary><ul>{analysis.warnings.map(w => <li key={w}>{w}</li>)}</ul><p>Processing method: <code>{analysis.method_version}</code></p></details></Paper>
  </>;
}

function App() {
  const [page, setPage] = useState<'reference' | 'planner'>('reference');
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let disposed = false; setError('');
    request<Analysis>('reference').then(r => { if (!disposed) setAnalysis(r); })
      .catch(() => { if (!disposed) setError('The reference analysis could not be loaded. Check that the local API is running.'); });
    return () => { disposed = true; };
  }, [attempt]);
  return <div className="app-shell">
    <a className="skip-link" href="#content">Skip to content</a>
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark" aria-hidden="true">∿</div><span>Scientific<br /> Dataset Copilot</span></div>
      <div className="nav-label">EXPLORE</div>
      <nav aria-label="Main navigation">
        <button className={page === 'reference' ? 'active' : ''} onClick={() => setPage('reference')} aria-current={page === 'reference' ? 'page' : undefined}>Reference analysis</button>
        <button className={page === 'planner' ? 'active' : ''} onClick={() => setPage('planner')} aria-current={page === 'planner' ? 'page' : undefined}>Query planner</button>
      </nav>
      <div className="sidebar-note"><span className="status-dot" />Development preview<p>Open data.<br />Visible methods.<br />Reproducible results.</p></div>
    </aside>
    <div className="workspace"><header><span>Explore with evidence</span><Chip label="Ocean / Climate" size="small" sx={{ bgcolor: '#e6f1eb', color: '#235c4a' }} /></header>
      <main id="content">
        <Alert severity="info" sx={{ mb: 4 }}>Local preview. Accounts, natural-language analysis, and self-service subscriptions are planned; they are not available in this version.</Alert>
        {error ? <Alert severity="error" action={<Button color="inherit" onClick={() => setAttempt(a => a + 1)}>Retry</Button>}>{error}</Alert> : !analysis ? <CircularProgress aria-label="Loading reference analysis" /> : page === 'reference' ? <Reference analysis={analysis} /> : <Planner analysis={analysis} />}
        <footer>Scientific Dataset Copilot · Source: NOAA NCEI · Exploratory scientific analysis</footer>
      </main>
    </div>
  </div>;
}

createRoot(document.getElementById('root')!).render(<ThemeProvider theme={theme}><CssBaseline /><App /></ThemeProvider>);

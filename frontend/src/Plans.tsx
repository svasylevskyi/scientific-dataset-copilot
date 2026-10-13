import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent,
  DialogContentText, DialogTitle, LinearProgress, MenuItem, Paper, Stack, TextField, Typography,
} from '@mui/material';
import { useAccount } from './Account';
import { request, type AdminPlan, type Plan, type PlanInput, type Usage, type Message } from './api';

const errorText = (error: unknown) => error instanceof Error ? error.message : 'Please try again.';
const dateText = (date: string) => new Date(date).toLocaleDateString('en-GB', { timeZone: 'UTC' });

function SignInNotice() {
  return <Paper className="panel"><Typography sx={{ mb: 2 }}>Sign in to view your plan and usage.</Typography>
    <Button href="#/signin" variant="contained">Sign in</Button></Paper>;
}

export function PlanUsageScreen() {
  const { user, loading } = useAccount();
  return <>
    <Typography variant="h4" component="h1" fontWeight={650} sx={{ mb: 3 }}>Plan and usage</Typography>
    {loading ? <CircularProgress aria-label="Loading account" /> : user ? <UsageDetails key={user.id} /> : <SignInNotice />}
  </>;
}

function UsageDetails() {
  const [data, setData] = useState<Usage | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { setData(await request<Usage>('account/usage')); }
    catch (error) { setError(errorText(error)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  return <>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    <Button onClick={load} disabled={loading} sx={{ mb: 2 }}>Refresh usage</Button>
    {loading && !data && <CircularProgress aria-label="Loading usage" />}
    {data && <>
      <Paper className="panel">
        <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap" sx={{ mb: 1 }}>
          <Typography variant="h5" component="h2">{data.plan.name}</Typography>
          <Chip label="Free" size="small" /><Chip label={data.status === 'active' ? 'Active' : 'Suspended'}
            color={data.status === 'active' ? 'success' : 'warning'} variant="outlined" size="small" />
        </Stack>
        <Typography color="text.secondary">{data.plan.description}</Typography>
        {!data.plan.active && <Typography sx={{ mt: 1 }}>This plan is archived for new assignments. Your existing access continues.</Typography>}
        <Typography sx={{ mt: 2 }}>Allowance period: {dateText(data.period_start)} to {dateText(data.period_end)} (reset at 00:00 UTC).</Typography>
        <div className="stats usage-stats">
          <Paper className="stat"><span>Completed</span><strong>{data.consumed}</strong><small>analyses this month</small></Paper>
          <Paper className="stat"><span>Reserved</span><strong>{data.reserved}</strong><small>pending this month</small></Paper>
          <Paper className="stat"><span>Remaining</span><strong>{data.remaining}</strong><small>of {data.plan.monthly_analyses} monthly</small></Paper>
        </div>
        <LinearProgress aria-label="Monthly allowance used or reserved" variant="determinate"
          value={data.plan.monthly_analyses === 0 ? 100 : Math.min(100, 100 * (data.consumed + data.reserved) / data.plan.monthly_analyses)} />
        <Typography variant="body2" sx={{ mt: 2 }}>{data.concurrent_reserved} of {data.plan.concurrent_analyses} simultaneous slots reserved · Up to {data.plan.max_date_range_days.toLocaleString()} days per analysis · Results retained for {data.plan.retention_days} days.</Typography>
        {data.blocked_reason && <Alert severity="warning" sx={{ mt: 2 }}>{data.blocked_reason}</Alert>}
      </Paper>
      <Alert severity="info" sx={{ mb: 3 }}>Run saved queries from Your analyses. The reference analysis and query previews do not use your allowance. Results expire according to the retention limit recorded when each run starts.</Alert>
      <Paper className="panel">
        <Typography variant="h6" component="h2">How usage works</Typography>
        <Typography>Each new analysis reserves one place in your monthly allowance. Successful runs count as completed; failed or cancelled runs release their reservation. Automatic retries of the same run do not count twice; starting another run creates a new reservation.</Typography>
        <Typography sx={{ mt: 1 }}>Allowances reset each calendar month in UTC, with no rollover. A run that spans two months counts in the month it was started. Pending runs still occupy a simultaneous slot.</Typography>
      </Paper>
      <Paper className="panel">
        <Typography variant="h6" component="h2">Recent usage</Typography>
        {data.recent.length === 0 ? <Typography sx={{ mt: 1 }}>No analyses yet. Your allowance is ready for live runs.</Typography> : <>
          <Typography variant="body2" color="text.secondary">The most recent 20 analysis reservations.</Typography>
          {data.recent.map(row => <Box className="session-row" key={row.id}>
            <div><Typography>{dateText(row.created_at)} · {row.status === 'consumed' ? 'Completed' : row.status === 'reserved' ? 'Reserved' : 'Released'}</Typography>
              <Typography variant="body2" color="text.secondary">Allowance month: {dateText(row.period_start)}{row.release_reason ? ` · ${row.release_reason === 'failed' ? 'Run failed' : 'Run cancelled'}` : ''}</Typography></div>
          </Box>)}
        </>}
      </Paper>
    </>}
  </>;
}

const limits = [
  { name: 'monthly_analyses', label: 'Analyses per month', min: 0, max: 10000, value: 20 },
  { name: 'concurrent_analyses', label: 'Simultaneous analyses', min: 1, max: 20, value: 1 },
  { name: 'max_date_range_days', label: 'Maximum date range (days)', min: 1, max: 3663, value: 3663 },
  { name: 'retention_days', label: 'Result retention (days)', min: 1, max: 3650, value: 30 },
] as const;

function PlanEditor({ plan, onSaved, onCancel }: { plan: AdminPlan | null; onSaved: () => Promise<void>; onCancel: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const data = new FormData(event.currentTarget);
    const body: PlanInput = {
      name: String(data.get('name')), description: String(data.get('description')), active: plan?.active ?? true,
      monthly_analyses: Number(data.get('monthly_analyses')), concurrent_analyses: Number(data.get('concurrent_analyses')),
      max_date_range_days: Number(data.get('max_date_range_days')), retention_days: Number(data.get('retention_days')),
    };
    try {
      await request<Plan>(plan ? `admin/plans/${plan.id}` : 'admin/plans', plan ? { ...body, version: plan.version } : body, plan ? 'PATCH' : 'POST');
      await onSaved();
    } catch (error) { setError(errorText(error)); }
    finally { setBusy(false); }
  }
  return <Paper className="panel">
    <Typography variant="h6" component="h2" sx={{ mb: 2 }}>{plan ? `Edit ${plan.name}` : 'Create a plan'}</Typography>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    <form onSubmit={submit}><Stack gap={2}>
      <TextField label="Plan name" name="name" required defaultValue={plan?.name ?? ''} slotProps={{ htmlInput: { maxLength: 80 } }} />
      <TextField label="Description" name="description" multiline minRows={2} defaultValue={plan?.description ?? ''} slotProps={{ htmlInput: { maxLength: 500 } }} />
      <div className="plan-limit-grid">{limits.map(field => <TextField key={field.name} label={field.label} name={field.name} type="number" required
        defaultValue={plan?.[field.name] ?? field.value} slotProps={{ htmlInput: { min: field.min, max: field.max, step: 1 } }} />)}</div>
      <Typography variant="body2" color="text.secondary">All plans are free in this increment. A monthly allowance of zero blocks new analyses. Edited limits apply to assigned workspaces immediately; existing usage is kept and accepted runs may finish. Retention changes apply to new reservations.</Typography>
      <Stack direction="row" gap={1}><Button type="submit" variant="contained" disabled={busy}>{busy ? 'Saving…' : 'Save plan'}</Button><Button onClick={onCancel} disabled={busy}>Cancel</Button></Stack>
    </Stack></form>
  </Paper>;
}

type Confirmation = { title: string; message: string; action: () => Promise<unknown> };

export function AdminPlansScreen() {
  const { user, loading } = useAccount();
  if (loading) return <CircularProgress aria-label="Loading account" />;
  if (!user) return <SignInNotice />;
  if (user.role !== 'admin') return <Alert severity="error">Administrator access is required.</Alert>;
  return <PlanAdministration key={user.id} />;
}

function PlanAdministration() {
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [editing, setEditing] = useState<AdminPlan | null | undefined>(undefined);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { setPlans(await request<AdminPlan[]>('admin/plans')); }
    catch (error) { setError(errorText(error)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function confirm() {
    if (!confirmation) return;
    setBusy(true); setError(''); setMessage('');
    try { await confirmation.action(); setConfirmation(null); setMessage('Changes saved.'); await load(); }
    catch (error) { setConfirmation(null); setError(errorText(error)); }
    finally { setBusy(false); }
  }
  function toggle(plan: AdminPlan) {
    const { id, version, name, description, monthly_analyses, concurrent_analyses, max_date_range_days, retention_days } = plan;
    setConfirmation({ title: `${plan.active ? 'Archive' : 'Activate'} ${plan.name}?`,
      message: plan.active ? 'Existing members keep this plan and its limits. It will no longer be available for new assignments.' : 'This plan will be available for new assignments.',
      action: () => request<Plan>(`admin/plans/${id}`, { name, description, monthly_analyses, concurrent_analyses, max_date_range_days, retention_days, version, active: !plan.active }, 'PATCH'),
    });
  }
  function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const email = String(data.get('email')); const planId = String(data.get('plan_id')); const status = String(data.get('status'));
    setConfirmation({ title: 'Change account plan?',
      message: `${email} will be assigned ${plans.find(plan => plan.id === planId)?.name} with ${status} analysis access. Existing usage will not reset, and accepted runs may finish.`,
      action: () => request<Message>('admin/plan-assignments', { email, plan_id: planId, status }),
    });
  }
  return <>
    <Typography variant="h4" component="h1" fontWeight={650}>Plan administration</Typography>
    <Typography color="text.secondary" sx={{ mt: 1, mb: 3 }}>Manage free plans, registration defaults and account allowances.</Typography>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    {message && <Alert severity="success" sx={{ mb: 2 }}>{message}</Alert>}
    <Stack direction="row" gap={1} sx={{ mb: 2 }}>
      <Button variant="contained" disabled={loading || busy} onClick={() => { setEditing(null); setMessage(''); }}>Create plan</Button>
      <Button disabled={loading || busy} onClick={() => { setEditing(undefined); void load(); }}>Refresh plans</Button>
    </Stack>
    {editing !== undefined && <PlanEditor key={editing ? `${editing.id}-${editing.version}` : 'new'} plan={editing}
      onCancel={() => setEditing(undefined)} onSaved={async () => { setEditing(undefined); setMessage('Plan saved.'); await load(); }} />}
    {loading && <CircularProgress aria-label="Loading plans" />}
    <div className="plan-grid">{plans.map(plan => <Paper className="panel" key={plan.id} component="section" aria-label={plan.name}>
      <Typography variant="h6" component="h2">{plan.name}</Typography>
      <Stack direction="row" gap={1} flexWrap="wrap" sx={{ my: 1 }}><Chip size="small" label="Free" />
        <Chip size="small" label={plan.active ? 'Active' : 'Archived'} variant="outlined" />
        {plan.is_default && <Chip size="small" color="success" label="Registration default" />}</Stack>
      <Typography>{plan.description}</Typography>
      <Typography sx={{ mt: 1 }}>{plan.monthly_analyses} analyses / month · {plan.concurrent_analyses} at a time</Typography>
      <Typography variant="body2">Up to {plan.max_date_range_days.toLocaleString()} days per analysis · {plan.retention_days} days retention</Typography>
      <Typography variant="body2" sx={{ mt: 1 }}>{plan.workspace_count} assigned workspaces</Typography>
      <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: 2 }}>
        <Button disabled={busy || loading} onClick={() => { setEditing(plan); setMessage(''); }}>Edit</Button>
        <Button disabled={busy || loading || plan.is_default} onClick={() => toggle(plan)}>{plan.active ? 'Archive' : 'Activate'}</Button>
        {!plan.is_default && plan.active && <Button disabled={busy || loading} onClick={() => setConfirmation({
          title: `Make ${plan.name} the default?`, message: 'New accounts will receive this plan. Existing accounts keep their assigned plans.',
          action: () => request<Plan>(`admin/plans/${plan.id}/default`, { version: plan.version }),
        })}>Make default</Button>}
      </Stack>
    </Paper>)}</div>
    {plans.some(plan => plan.active) && <Paper className="panel">
      <Typography variant="h6" component="h2" sx={{ mb: 2 }}>Assign an account plan</Typography>
      <form onSubmit={assign}><Stack gap={2}>
        <TextField label="Account email" name="email" type="email" required />
        <TextField select label="Plan to assign" name="plan_id" required key={plans.map(p => `${p.id}-${p.active}`).join(',')}
          defaultValue={plans.find(plan => plan.active && plan.is_default)?.id ?? plans.find(plan => plan.active)?.id}>
          {plans.filter(plan => plan.active).map(plan => <MenuItem key={plan.id} value={plan.id}>{plan.name}</MenuItem>)}
        </TextField>
        <TextField select label="Analysis access" name="status" defaultValue="active"><MenuItem value="active">Active</MenuItem><MenuItem value="suspended">Suspended</MenuItem></TextField>
        <Typography variant="body2" color="text.secondary">Suspension blocks new analyses. It does not disable sign-in, remove results, or cancel accepted work.</Typography>
        <Button type="submit" variant="outlined" disabled={busy || loading}>Save assignment</Button>
      </Stack></form>
    </Paper>}
    <Dialog open={confirmation !== null} onClose={() => { if (!busy) setConfirmation(null); }} aria-labelledby="plan-confirm-title">
      <DialogTitle id="plan-confirm-title">{confirmation?.title}</DialogTitle>
      <DialogContent><DialogContentText>{confirmation?.message}</DialogContentText></DialogContent>
      <DialogActions><Button disabled={busy} onClick={() => setConfirmation(null)}>Cancel</Button><Button disabled={busy} onClick={confirm}>{busy ? 'Saving…' : 'Confirm'}</Button></DialogActions>
    </Dialog>
  </>;
}

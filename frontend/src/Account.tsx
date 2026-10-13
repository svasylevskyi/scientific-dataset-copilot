import { createContext, useCallback, useContext, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Divider, Paper, Stack, TextField, Typography } from '@mui/material';
import { ApiError, request, type Account, type AccountSession, type AdminSummary, type Message } from './api';

const errorText = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Please try again.';
const AuthContext = createContext<{
  user: Account | null; loading: boolean; error: string;
  setUser: (user: Account | null) => void; reload: () => Promise<void>;
}>({ user: null, loading: true, error: '', setUser: () => {}, reload: async () => {} });

export function useAccount() { return useContext(AuthContext); }

export function AccountProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const reload = useCallback(async () => {
    try { setUser(await request<Account>('auth/me')); setError(''); }
    catch (e) { setUser(null); setError(e instanceof ApiError && e.status === 401 ? '' : errorText(e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    void reload();
    const signedOut = () => setUser(null);
    window.addEventListener('sdc-signed-out', signedOut);
    window.addEventListener('focus', reload);
    return () => { window.removeEventListener('sdc-signed-out', signedOut); window.removeEventListener('focus', reload); };
  }, [reload]);
  useEffect(() => {
    if (!user) return;
    const renew = async () => {
      try { await request<Message>('auth/refresh', {}); }
      catch (e) { if (!(e instanceof ApiError && e.status === 409)) setError(errorText(e)); }
    };
    // Login issues a fresh token; rotate periodically while the account is open.
    // Conflicting tabs keep the winning cookie.
    const timer = window.setInterval(renew, 15 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [user?.id]);
  return <AuthContext.Provider value={{ user, loading, error, setUser, reload }}>{children}</AuthContext.Provider>;
}

export function useRoute() {
  const [hash, setHash] = useState(window.location.hash || '#/reference');
  useEffect(() => {
    const changed = () => setHash(window.location.hash || '#/reference');
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  return { page: hash.slice(2).split('?')[0], hash };
}

function PasswordField({ label, name, autoComplete = 'new-password' }: { label: string; name: string; autoComplete?: string }) {
  return <TextField label={label} name={name} type="password" autoComplete={autoComplete} required fullWidth
    slotProps={{ htmlInput: { minLength: autoComplete === 'new-password' ? 12 : 1, maxLength: 128 } }} />;
}

function matchingPassword(data: FormData): string {
  const password = String(data.get('password') ?? '');
  if (password !== data.get('confirm')) throw new Error('Passwords do not match.');
  return password;
}

type AuthPage = 'signin' | 'signup' | 'forgot' | 'resend' | 'verify' | 'reset' | 'email';
const titles: Record<AuthPage, string> = {
  signin: 'Sign in', signup: 'Create your account', forgot: 'Reset your password',
  resend: 'Request a verification email', verify: 'Verify your email', reset: 'Choose a new password', email: 'Confirm your new email',
};

export function AuthScreen({ page }: { page: AuthPage }) {
  const { setUser } = useAccount();
  const [token] = useState(() => new URLSearchParams(window.location.hash.split('?')[1]).get('token') ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const linkPage = ['verify', 'reset', 'email'].includes(page);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setMessage('');
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    try {
      const email = String(data.get('email') ?? '');
      if (page === 'signin') {
        setUser(await request<Account>('auth/login', { email, password: data.get('password') }));
        window.location.hash = '/account';
      } else {
        let result: Message;
        if (page === 'signup') result = await request<Message>('auth/register', { email, name: data.get('name'), password: matchingPassword(data) });
        else if (page === 'forgot') result = await request<Message>('auth/forgot-password', { email });
        else if (page === 'resend') result = await request<Message>('auth/resend-verification', { email });
        else if (page === 'reset') result = await request<Message>('auth/reset-password', { token, password: matchingPassword(data) });
        else result = await request<Message>(page === 'verify' ? 'auth/verify' : 'auth/confirm-email', { token });
        if (page === 'reset' || page === 'email') setUser(null);
        setMessage(result.message); form.reset();
        if (linkPage) window.history.replaceState(null, '', `#/${page}`);
      }
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  return <Box className="auth-screen">
    <Typography variant="h4" component="h1" fontWeight={650}>{titles[page]}</Typography>
    <Typography color="text.secondary" sx={{ mt: 1, mb: 3 }}>
      {page === 'signup' ? 'Your personal workspace for scientific exploration.'
        : page === 'signin' ? 'Welcome back to Scientific Dataset Copilot.'
        : linkPage ? 'Confirm below to complete your request.' : 'Enter your email and we will send you a secure link.'}
    </Typography>
    <Paper className="panel">
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {message && <Alert severity="success" sx={{ mb: 2 }}>{message}</Alert>}
      {linkPage && !token && !message ? <Alert severity="warning">Open the full link from your email. If it has expired, request a new one.</Alert> : !(message && linkPage) &&
        <form onSubmit={submit}>
          <Stack spacing={2}>
            {page === 'signup' && <TextField label="Name" name="name" autoComplete="name" required slotProps={{ htmlInput: { maxLength: 100 } }} />}
            {!linkPage && <TextField label="Email" name="email" type="email" autoComplete="email" required />}
            {['signin', 'signup', 'reset'].includes(page) && <PasswordField label="Password" name="password" autoComplete={page === 'signin' ? 'current-password' : 'new-password'} />}
            {['signup', 'reset'].includes(page) && <>
              <PasswordField label="Confirm password" name="confirm" />
              <Typography variant="body2" color="text.secondary">Use 12–128 characters. A long, unique passphrase works well.</Typography>
            </>}
            <Button type="submit" variant="contained" disabled={busy}>{busy ? 'Please wait…' : titles[page]}</Button>
          </Stack>
        </form>}
      <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: 2 }}>
        {page !== 'signin' && <Button href="#/signin">Sign in</Button>}
        {page === 'signin' && <><Button href="#/signup">Create account</Button><Button href="#/forgot">Forgot password?</Button></>}
        {['signin', 'signup', 'verify'].includes(page) && <Button href="#/resend">Resend verification</Button>}
        {page === 'reset' && <Button href="#/forgot">Request a new reset link</Button>}
      </Stack>
    </Paper>
  </Box>;
}

function EditForm({ title, button, children, action }: {
  title: string; button: string; children: ReactNode; action: (data: FormData) => Promise<string>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    const form = event.currentTarget;
    try { setMessage(await action(new FormData(form))); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  return <Paper className="panel"><Typography variant="h6" component="h2" sx={{ mb: 2 }}>{title}</Typography>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    {message && <Alert severity="success" sx={{ mb: 2 }}>{message}</Alert>}
    <form onSubmit={submit}><Stack spacing={2}>{children}<Button type="submit" variant="outlined" disabled={busy}>{busy ? 'Saving…' : button}</Button></Stack></form>
  </Paper>;
}

function SessionList() {
  const { setUser } = useAccount();
  const [sessions, setSessions] = useState<AccountSession[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setSessions(await request<AccountSession[]>('account/sessions')); setError(''); }
    catch (e) { setError(errorText(e)); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function revoke(session?: AccountSession) {
    setBusy(true); setError('');
    try {
      if (session) await request<Message>(`account/sessions/${session.id}`, {}, 'DELETE');
      else await request<Message>('account/logout-all', {});
      if (!session || session.current) { setUser(null); window.location.hash = '/signin'; }
      else await load();
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  return <Paper className="panel">
    <Typography variant="h6" component="h2">Active sessions</Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Sign out a session you no longer need.</Typography>
    {error && <Alert severity="error" action={<Button onClick={load} color="inherit">Retry</Button>}>{error}</Alert>}
    {sessions.map(session => <Box className="session-row" key={session.id}>
      <div><Typography variant="body2">{session.current ? 'This browser' : 'Another session'}</Typography><Typography variant="caption" color="text.secondary">Signed in {new Date(session.created_at).toLocaleString()}</Typography></div>
      <Button disabled={busy} onClick={() => revoke(session)}>Sign out{session.current ? ' here' : ' session'}</Button>
    </Box>)}
    <Divider sx={{ my: 2 }} /><Button color="error" disabled={busy} onClick={() => revoke()}>Sign out all devices</Button>
  </Paper>;
}

function AdminPanel() {
  const [data, setData] = useState<AdminSummary | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { request<AdminSummary>('admin/summary').then(setData).catch(e => setError(errorText(e))); }, []);
  return <Paper className="panel"><Typography variant="h6" component="h2">Account administration</Typography>
    {error ? <Alert severity="error">{error}</Alert> : data ? <Typography sx={{ mt: 1 }}>{data.users} accounts · {data.verified_users} verified · {data.workspaces} personal workspaces</Typography> : <CircularProgress size={24} />}
    <Button href="#/admin/plans" sx={{ mt: 2 }}>Manage plans</Button>
  </Paper>;
}

export function AccountScreen() {
  const { user, loading, error, setUser, reload } = useAccount();
  if (loading) return <CircularProgress aria-label="Loading account" />;
  if (!user) return <Box className="auth-screen"><Typography variant="h4" component="h1">Your account</Typography>
    {error && <Alert severity="error" sx={{ my: 2 }} action={<Button color="inherit" onClick={reload}>Retry</Button>}>{error}</Alert>}
    <Typography sx={{ my: 2 }}>Sign in to access your personal workspace.</Typography><Button variant="contained" href="#/signin">Sign in</Button><Button href="#/signup">Create account</Button></Box>;
  const signedOut = (message: string) => { setUser(null); window.location.hash = '/signin'; window.sessionStorage.setItem('sdc-account-notice', message); return message; };
  return <>
    <div className="title-row"><div><Typography variant="h4" component="h1" fontWeight={650}>Your account</Typography><Typography color="text.secondary" sx={{ mt: 1, mb: 3 }}>{user.workspace.name} · {user.email}</Typography></div><Chip label="Email verified" color="success" variant="outlined" /></div>
    <div className="account-grid">
      <div>
        <EditForm title="Profile" button="Save profile" action={async data => {
          const updated = await request<Account>('account', { name: data.get('name') }, 'PATCH'); setUser(updated); return 'Profile saved.';
        }}><TextField label="Name" name="name" defaultValue={user.name} autoComplete="name" required slotProps={{ htmlInput: { maxLength: 100 } }} /><TextField label="Email" value={user.email} slotProps={{ input: { readOnly: true } }} /></EditForm>
        <EditForm title="Change email" button="Send confirmation link" action={async data => (await request<Message>('account/email', { email: data.get('email'), current_password: data.get('current') })).message}>
          <Typography variant="body2" color="text.secondary">Your current email stays active until you confirm the new address. Confirmation signs out all sessions.</Typography>
          <TextField label="New email" name="email" type="email" autoComplete="email" required />
          <PasswordField label="Current password" name="current" autoComplete="current-password" />
        </EditForm>
      </div>
      <div>
        <EditForm title="Change password" button="Update password" action={async data => signedOut((await request<Message>('account/password', { current_password: data.get('current'), password: matchingPassword(data) })).message)}>
          <Typography variant="body2" color="text.secondary">Use 12–128 characters. Changing your password signs out all sessions.</Typography>
          <PasswordField label="Current password" name="current" autoComplete="current-password" />
          <PasswordField label="New password" name="password" /><PasswordField label="Confirm new password" name="confirm" />
        </EditForm>
        <SessionList />
      </div>
    </div>
    {user.role === 'admin' && <AdminPanel />}
  </>;
}

export function AccountNotice() {
  const [notice] = useState(() => { const value = window.sessionStorage.getItem('sdc-account-notice'); window.sessionStorage.removeItem('sdc-account-notice'); return value; });
  return notice ? <Alert severity="success" sx={{ mb: 2 }}>{notice}</Alert> : null;
}

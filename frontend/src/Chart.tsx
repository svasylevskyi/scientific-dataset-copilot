import { useEffect, useRef, useState } from 'react';
import { Alert, Button } from '@mui/material';
import Plotly from 'plotly.js-basic-dist-min';
import type { Analysis } from './api';

export default function Chart({ analysis }: { analysis: Analysis }) {
  const root = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const node = root.current;
    if (!node) return;
    let disposed = false;
    Plotly.newPlot(node, [{
      x: analysis.months.map(m => m.month),
      y: analysis.months.map(m => m.mean_celsius),
      type: 'scatter', mode: analysis.months.length === 1 ? 'markers' : 'lines', connectgaps: false,
      line: { color: '#168578', width: 2.5 },
      hovertemplate: '%{x|%b %Y}<br>%{y:.2f} °C<extra></extra>',
    }], {
      autosize: true, height: 390,
      margin: { t: 20, r: 18, b: 55, l: 58 },
      font: { family: 'system-ui, sans-serif', size: 12, color: '#55676a' },
      paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
      xaxis: { type: 'date', dtick: analysis.months.length > 24 ? 'M12' : 'M1', tickformat: analysis.months.length > 24 ? '%Y' : '%b %Y', showgrid: false, zeroline: false },
      yaxis: { title: { text: 'Sea surface temperature (°C)' }, gridcolor: '#e5eeeb', zeroline: false },
      hovermode: 'x unified', dragmode: false,
    }, { responsive: true, displayModeBar: false, scrollZoom: false })
      .then(() => { if (disposed) Plotly.purge(node); else setReady(true); })
      .catch(() => { if (!disposed) setError('The chart could not be displayed. CSV data remain available.'); });
    return () => { disposed = true; Plotly.purge(node); };
  }, [analysis]);

  async function download() {
    if (!root.current || !ready) return;
    try {
      await Plotly.downloadImage(root.current, {
        format: 'png', width: 1400, height: 600, filename: `${analysis.plan.request.region_id}-sst-${analysis.plan.request.start}-${analysis.plan.request.end}`,
      });
    } catch { setError('The image could not be exported. CSV data remain available.'); }
  }

  return <>
    {error && <Alert severity="error">{error}</Alert>}
    <div ref={root} role="img" aria-label={`Monthly mean sea surface temperature: ${analysis.plan.region.name}, ${analysis.plan.request.start} to ${analysis.plan.request.end}. Exact values are available in the CSV export.`} />
    <Button variant="outlined" onClick={download} disabled={!ready}>Download chart</Button>
  </>;
}

// The History page: hourly (7 days) or daily (30 days, 1 year) averages from /api/history
Chart.defaults.color = '#D4D4D8';
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.font.size = 12;

// Bottom to top, as in the dashboard's 24-hour mix
const FUELS = [['nuclear', 'Nuclear'], ['ccgt', 'Gas (CCGT)'], ['ocg', 'Gas (OCGT)'], ['other', 'Other'], ['imports', 'Imports'],
    ['biomass', 'Biomass'], ['pumped_storage', 'Pumped storage'], ['battery', 'Batteries (est.)'], ['hydro', 'Hydro'],
    ['solar', 'Solar'], ['lv_wind', 'Small wind'], ['wind', 'Wind']];
const RANGES = ['7d', '30d', '1y'];
const GRID = '#3F3F46', MUTED = '#A1A1AA';

let config = null, hist = null, mixMode = 'GW';
let range = RANGES.includes(new URLSearchParams(location.search).get('range')) ? new URLSearchParams(location.search).get('range') : '7d';
const charts = {};

const setText = (id, text) => { const el = document.getElementById(id); if (el) el.innerText = text; };
const hourly = () => hist.unit === 'hour';
const dateOf = t => new Date(t * 1000);
const dayLabel = t => dateOf(t).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
const timeLabel = t => dateOf(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const bucketLabel = t => hourly() ? `${dayLabel(t)}, ${timeLabel(t)}` : dayLabel(t);
const momentLabel = t => `${dayLabel(t)} ${timeLabel(t)}`;
const gw = mw => (mw / 1000).toFixed(1);
const durationText = mins => {
    const secs = Math.round(mins * 60);
    if (secs < 60) return `${secs}s`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, '0')}s`;
    return `${Math.floor(secs / 3600)}h ${String(Math.floor(secs % 3600 / 60)).padStart(2, '0')}m`;
};
const fuelColour = key => (config.fuels || {})[key] || { lv_wind: '#5FB035', battery: '#A78BFA' }[key] || MUTED;
const rgba = (hex, alpha) => { const n = parseInt(hex.replace('#', ''), 16); return `rgba(${n >> 16 & 255}, ${n >> 8 & 255}, ${n & 255}, ${alpha})`; };

function stylePills(containerId, attr, value, size) {
    const active = `${size} rounded-full bg-ui-grey text-white font-semibold shadow-sm transition-all`;
    const idle = `${size} rounded-full text-ui-light hover:text-white transition-all`;
    document.querySelectorAll(`#${containerId} button`).forEach(b => b.className = b.dataset[attr] === value ? active : idle);
}

function setRange(r) {
    range = r;
    history.replaceState(null, '', `?range=${r}`);
    load();
}

function setMixMode(mode) {
    mixMode = mode;
    stylePills('mix-pills', 'mode', mode, 'px-4 py-1');
    if (hist) drawMix();
}

function load() {
    stylePills('range-pills', 'range', range, 'px-5 py-1.5');
    setText('range-note', 'Loading…');
    Promise.all([
        config ? Promise.resolve(config) : fetch('/api/config').then(r => r.json()),
        fetch(`/api/history?range=${range}`).then(r => r.json())
    ]).then(([c, d]) => { config = c; hist = d; render(); })
      .catch(() => setText('range-note', "Couldn't load the history."));
}

// x axis: day names at midnight (hourly), dates (30 days) or month names (1 year)
function xScale(stacked = false) {
    return {
        stacked, grid: { display: false },
        ticks: { color: MUTED, maxRotation: 0, autoSkip: false, callback: function (v, i) {
            const d = dateOf(hist.t[i]);
            if (hourly()) return d.getHours() === 0 ? d.toLocaleDateString([], { weekday: 'short', day: 'numeric' }) : null;
            if (hist.t.length > 60) return d.getDate() === 1 ? d.toLocaleDateString([], { month: 'short' }) : null;
            const every = Math.ceil(hist.t.length / (this.chart.width < 500 ? 4 : 10));
            return (hist.t.length - 1 - i) % every === 0 ? d.toLocaleDateString([], { day: 'numeric', month: 'short' }) : null;
        } }
    };
}

function makeChart(id, config) {
    if (charts[id]) charts[id].destroy();
    const canvas = document.getElementById(id);
    if (!canvas) return;
    config.options = Object.assign({ responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false } }, config.options);
    charts[id] = new Chart(canvas.getContext('2d'), config);
}

const titleCallback = items => bucketLabel(hist.t[items[0].dataIndex]);

function render() {
    const first = hist.t[0];
    setText('range-note', !hist.t.length ? 'No data yet.'
        : `${hourly() ? 'Hourly' : 'Daily'} averages from ${dayLabel(first)}` +
          (range === '1y' && Date.now() / 1000 - first < 360 * 86400 ? ', when the history starts' : ''));
    renderSummary();
    drawMix();
    drawCarbon();
    drawPrice();
    drawFrequency();
    drawFlow();
    drawHome();
}

function renderSummary() {
    const s = hist.summary, unit = hourly() ? 'hour' : 'day';
    if (s.demand_avg != null) {
        setText('sum-demand', `${gw(s.demand_avg)} GW`);
        setText('sum-demand-note', `Peak ${gw(s.demand_peak[0])} GW (${momentLabel(s.demand_peak[1])}), lowest ${gw(s.demand_low[0])} GW (${momentLabel(s.demand_low[1])}).`);
    }
    if (s.share.low_carbon != null) {
        setText('sum-lowcarbon', `${s.share.low_carbon.toFixed(0)}%`);
        setText('sum-lowcarbon-note', `Wind, solar, hydro, nuclear and biomass. Gas ${s.share.gas.toFixed(0)}%, imports ${s.share.imports.toFixed(0)}%.`);
        setText('sum-wind', `${s.share.wind.toFixed(1)}%`);
        setText('sum-wind-note', s.wind_max ? `Of supply. Highest ${gw(s.wind_max[0])} GW (${momentLabel(s.wind_max[1])}).` : 'Of supply.');
        setText('sum-solar', `${s.share.solar.toFixed(1)}%`);
        setText('sum-solar-note', s.solar_max ? `Of supply. Highest ${gw(s.solar_max[0])} GW (${momentLabel(s.solar_max[1])}).` : 'Of supply.');
    }
    if (s.carbon_avg != null) {
        setText('sum-carbon', `${Math.round(s.carbon_avg)} g`);
        setText('sum-carbon-note', `gCO₂/kWh. Greenest ${unit} ${Math.round(s.carbon_best[0])} g (${bucketLabel(s.carbon_best[1])}), highest ${Math.round(s.carbon_worst[0])} g (${bucketLabel(s.carbon_worst[1])}).`);
    }
    if (s.mip_avg != null) {
        setText('sum-price', `£${s.mip_avg.toFixed(0)}/MWh`);
        setText('sum-price-note', `Cheapest ${unit} £${s.mip_cheapest[0].toFixed(0)} (${bucketLabel(s.mip_cheapest[1])}), dearest £${s.mip_dearest[0].toFixed(0)} (${bucketLabel(s.mip_dearest[1])}).` +
            (s.agile_avg != null ? ` My Agile import averaged ${s.agile_avg.toFixed(1)}p/kWh.` : ''));
    }
    const f = s.frequency;
    setText('sum-freq-label', `Outside ${hist.low}–${hist.high} Hz`);
    if (f) {
        const firstFreq = hist.frequency.findIndex(x => x);
        setText('sum-freq', f.outside_min ? durationText(f.outside_min) : 'None');
        setText('sum-freq-note', `${f.outside_pct.toFixed(2)}% of the time. Range ${f.min.toFixed(2)}–${f.max.toFixed(2)} Hz.` +
            (firstFreq > 0 ? ` Readings from ${dayLabel(hist.t[firstFreq])}.` : ''));
    } else { setText('sum-freq', '---'); setText('sum-freq-note', 'No 15-second readings for this period yet.'); }
    const h = s.home;
    setText('sum-home', `${Math.round(h.solar).toLocaleString()} kWh`);
    setText('sum-home-note', `Home used ${Math.round(h.home).toLocaleString()} kWh, imported ${Math.round(h.import).toLocaleString()}, exported ${Math.round(h.export).toLocaleString()}.`);
}

function drawMix() {
    stylePills('mix-pills', 'mode', mixMode, 'px-4 py-1');
    const inGw = mixMode === 'GW';
    const fuels = FUELS.filter(([k]) => (hist.mix[k] || []).some(v => v));
    const totals = hist.t.map((_, i) => fuels.reduce((a, [k]) => a + (hist.mix[k][i] || 0), 0));
    // A missing fuel in a bucket that has data is 0 (keeps the stack intact); a bucket with no data at all is a gap
    const value = (k, i) => !totals[i] ? null : inGw ? (hist.mix[k][i] || 0) / 1000 : (hist.mix[k][i] || 0) / totals[i] * 100;
    const datasets = fuels.map(([k, name]) => ({
        type: hourly() ? 'line' : 'bar', label: name, data: hist.t.map((_, i) => value(k, i)),
        backgroundColor: fuelColour(k), borderColor: 'transparent', borderWidth: 0, fill: true, pointRadius: 0, tension: 0.3, stack: 'mix', order: 1,
        barPercentage: 1, categoryPercentage: hist.t.length > 60 ? 1 : 0.85
    }));
    if (inGw) datasets.push({ type: 'line', label: 'Demand', data: hist.demand.map(v => v == null ? null : v / 1000), borderColor: (config.demand || {}).dashed || '#FFFFFF',
        borderDash: [5, 5], borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3, order: 0 });
    makeChart('chartMix', {
        data: { labels: hist.t, datasets },
        options: {
            plugins: {
                legend: { labels: { color: '#D4D4D8', boxWidth: 12 } },
                tooltip: { itemSort: (a, b) => b.datasetIndex - a.datasetIndex, callbacks: { title: titleCallback,
                    label: ctx => ctx.raw == null ? null : `${ctx.dataset.label}: ${ctx.raw.toFixed(inGw ? 2 : 1)}${inGw ? ' GW' : '%'}` } }
            },
            scales: { x: xScale(true), y: { stacked: true, min: 0, max: inGw ? undefined : 100, grid: { color: GRID }, ticks: { color: MUTED, callback: v => inGw ? `${v} GW` : `${v}%` } } }
        }
    });
}

function drawCarbon() {
    const c = config.carbon || {}, colour = v => v < 100 ? c.low : v < 200 ? c.med : c.high;
    makeChart('chartCarbon', {
        type: 'line',
        data: { labels: hist.t, datasets: [{ label: 'Carbon intensity', data: hist.carbon, borderWidth: 2, pointRadius: 0, tension: 0.3, spanGaps: false,
            borderColor: c.med, segment: { borderColor: ctx => colour((ctx.p0.parsed.y + ctx.p1.parsed.y) / 2) } }] },
        options: {
            plugins: { legend: { display: false }, tooltip: { callbacks: { title: titleCallback, label: ctx => ctx.raw == null ? null : `${Math.round(ctx.raw)} gCO₂/kWh` } } },
            scales: { x: xScale(), y: { min: 0, grid: { color: GRID }, ticks: { color: MUTED, callback: v => `${v} g` } } }
        }
    });
}

function drawPrice() {
    const blue = (config.mi_price || {}).color_med || '#3B82F6', agile = (config.octopus || {}).color_imp || '#FF00A0';
    makeChart('chartPrice', {
        type: 'line',
        data: { labels: hist.t, datasets: [
            { label: 'Highest', data: hist.mip_max, borderColor: 'transparent', backgroundColor: rgba(blue, 0.18), pointRadius: 0, fill: '+1', tension: 0.3, yAxisID: 'y' },
            { label: 'Lowest', data: hist.mip_min, borderColor: 'transparent', pointRadius: 0, fill: false, tension: 0.3, yAxisID: 'y' },
            { label: 'Market index (average)', data: hist.mip, borderColor: blue, borderWidth: 2, pointRadius: 0, tension: 0.3, yAxisID: 'y' },
            { label: 'Agile import', data: hist.agile_import, borderColor: agile, borderWidth: 1.5, borderDash: [4, 3], pointRadius: 0, tension: 0.3, yAxisID: 'pence' }
        ] },
        options: {
            plugins: {
                legend: { labels: { color: '#D4D4D8', boxWidth: 12, filter: item => item.datasetIndex >= 2 } },
                tooltip: { callbacks: { title: titleCallback, label: ctx => ctx.raw == null ? null
                    : ctx.dataset.yAxisID === 'pence' ? `Agile import: ${ctx.raw.toFixed(1)}p/kWh` : `${ctx.dataset.label}: £${ctx.raw.toFixed(2)}/MWh` } }
            },
            scales: {
                x: xScale(),
                y: { grid: { color: GRID }, ticks: { color: MUTED, callback: v => `£${v}` } },
                pence: { position: 'right', grid: { display: false }, ticks: { color: MUTED, callback: v => `${v}p` } }
            }
        }
    });
}

function drawFrequency() {
    const limit = (config.frequency || {}).color_limit || '#F6643C';
    const f = hist.frequency, low = hist.low, high = hist.high;
    // Always show the limits; round the axis to 0.05 Hz (bar charts would otherwise start it at 0)
    const seen = f.filter(x => x);
    const lo = Math.floor((Math.min(low, ...seen.map(x => x.min)) - 0.01) * 20) / 20, hi = Math.ceil((Math.max(high, ...seen.map(x => x.max)) + 0.01) * 20) / 20;
    setText('freq-chart-note', `Lowest to highest reading each ${hourly() ? 'hour' : 'day'} (highlighted when outside ${low}–${high} Hz), and minutes outside those limits.`);
    makeChart('chartFreq', {
        data: { labels: hist.t, datasets: [
            { type: 'line', label: 'Minutes outside', data: f.map(x => x ? x.outside_min : null), borderColor: limit, borderWidth: 1.5, pointRadius: hourly() ? 0 : 2,
              pointBackgroundColor: limit, tension: 0, yAxisID: 'mins', order: 0 },
            { type: 'bar', label: 'Range', data: f.map(x => x ? [x.min, x.max] : null), yAxisID: 'hz', order: 1, borderRadius: 2,
              backgroundColor: f.map(x => x && (x.min < low || x.max > high) ? limit : 'rgba(212, 212, 216, 0.55)') },
            { type: 'line', label: 'Limits', data: hist.t.map(() => low), borderColor: rgba(limit, 0.6), borderDash: [3, 3], borderWidth: 1, pointRadius: 0, yAxisID: 'hz', order: 2 },
            { type: 'line', label: '', data: hist.t.map(() => high), borderColor: rgba(limit, 0.6), borderDash: [3, 3], borderWidth: 1, pointRadius: 0, yAxisID: 'hz', order: 2 }
        ] },
        options: {
            plugins: {
                legend: { labels: { color: '#D4D4D8', boxWidth: 12, filter: item => item.text !== '' } },
                tooltip: { filter: item => item.datasetIndex < 2, callbacks: { title: titleCallback, label: ctx => {
                    const x = f[ctx.dataIndex];
                    if (!x) return null;
                    return ctx.datasetIndex === 1 ? `${x.min.toFixed(3)} to ${x.max.toFixed(3)} Hz` : `Outside the limits: ${durationText(x.outside_min)}`;
                } } }
            },
            scales: {
                x: xScale(),
                hz: { position: 'left', beginAtZero: false, min: lo, max: hi, grid: { color: GRID }, ticks: { color: MUTED, callback: v => v.toFixed(2) } },
                mins: { position: 'right', min: 0, suggestedMax: 5, grid: { display: false }, ticks: { color: MUTED, callback: v => `${v}m` } }
            }
        }
    });
}

function drawFlow() {
    const imports = fuelColour('imports'), exports = (config.flow || {}).exports || '#FF00A0';
    makeChart('chartFlow', {
        type: 'bar',
        data: { labels: hist.t, datasets: [{ label: 'Net flow', data: hist.net_flow.map(v => v == null ? null : v / 1000),
            backgroundColor: hist.net_flow.map(v => v >= 0 ? imports : exports), borderRadius: 2 }] },
        options: {
            plugins: { legend: { display: false }, tooltip: { callbacks: { title: titleCallback,
                label: ctx => ctx.raw == null ? null : `${ctx.raw >= 0 ? 'Importing' : 'Exporting'} ${Math.abs(ctx.raw).toFixed(2)} GW` } } },
            scales: { x: xScale(), y: { grid: { color: GRID }, ticks: { color: MUTED, callback: v => `${v} GW` } } }
        }
    });
}

function drawHome() {
    const theme = config.theme || {};
    const series = [['solar', 'Solar', fuelColour('solar')], ['home', 'Home use', '#D4D4D8'], ['import', 'Imported', theme.brand_cyan || '#30C5D5'], ['export', 'Exported', theme.tesla_green || '#00D241']];
    makeChart('chartHome', {
        type: hourly() ? 'line' : 'bar',
        data: { labels: hist.t, datasets: series.map(([k, label, colour]) => ({ label, data: hist.home[k], backgroundColor: hourly() ? 'transparent' : colour,
            borderColor: colour, borderWidth: hourly() ? 1.5 : 0, pointRadius: 0, tension: 0.3, borderRadius: 2 })) },
        options: {
            plugins: {
                legend: { labels: { color: '#D4D4D8', boxWidth: 12 } },
                tooltip: { callbacks: { title: titleCallback, label: ctx => ctx.raw == null ? null : `${ctx.dataset.label}: ${ctx.raw.toFixed(hourly() ? 2 : 1)} kWh` } }
            },
            scales: { x: xScale(), y: { min: 0, grid: { color: GRID }, ticks: { color: MUTED, callback: v => `${v} kWh` } } }
        }
    });
}

load();

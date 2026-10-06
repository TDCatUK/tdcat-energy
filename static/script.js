Chart.register(ChartDataLabels);
Chart.defaults.plugins.datalabels = { display: false };
Chart.defaults.color = '#D4D4D8'; 
Chart.defaults.font.family = "'Inter', sans-serif"; 
Chart.defaults.font.size = 13;

// pw_level is the gateway's raw state of charge. The Tesla app hides a 5% reserve, so it shows (raw - 5) / 0.95.
const appBatteryLevel = (raw) => Math.min(100, Math.max(0, (raw - 5) / 0.95));

const formatGW = (mw) => (mw / 1000).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});

const fuelInfoText = {
    "CCGT": "High-efficiency power stations that use both a gas and a steam turbine together to produce up to 50% more electricity from the same fuel.",
    "Wind": "Total generation from both onshore and offshore wind farms across the UK.",
    "LV Wind": "Estimated generation from smaller, embedded wind turbines connected to the local distribution network.",
    "Nuclear": "Baseload power provided by the UK's active nuclear reactor fleet. Extremely low carbon but highly inflexible.",
    "Solar": "Estimated national solar generation, calculated by scaling up sample data from thousands of monitored PV systems.",
    "Biomass": "Power stations (like Drax) that burn organic matter (wood pellets). Categorized as renewable, though highly debated.",
    "Hydro": "Traditional hydro-electric generation from flowing water and reservoirs.",
    "Pumped Storage": "Reservoirs that release water through turbines during high demand, and pump water back uphill when grid power is cheap.",
    "OCG": "Fast-starting but inefficient open-cycle gas turbines used strictly to cover sudden peaks in national demand.",
    "Other": "Miscellaneous generation sources not strictly defined by major categories. Also absorbs trace outputs from decommissioned fossil networks."
};

const interconnectorCaps = {
    "France (ElecLink)": 1.0, "Ireland (EWIC)": 0.5, "France (IFA)": 2.0, "France (IFA2)": 1.0,
    "Ireland (Moyle)": 0.5, "Netherlands (BritNed)": 1.0, "Belgium (Nemo)": 1.0, 
    "Norway (NSL)": 1.4, "Denmark (Viking)": 1.4, "Ireland (Greenlink)": 0.5
};

const LEGACY_ICONS = {
    'sun': 'fa-solid fa-sun',
    'globe': 'fa-solid fa-earth-europe',
    'factory': 'fa-solid fa-industry',
    'wind': 'fa-solid fa-wind',
    'battery': 'fa-solid fa-battery-half',
    'home': 'fa-solid fa-house',
    'export': 'fa-solid fa-file-export'
};

function getValidIcon(val) {
    if (!val) return 'fa-solid fa-circle';
    if (val.includes('fa-')) return val;
    return LEGACY_ICONS[val] || 'fa-solid fa-' + val;
}

const sortOrder = ["Wind", "LV Wind", "Solar", "Hydro", "Biomass", "Nuclear", "Imports", "Other", "OCG", "CCGT", "Pumped Storage"];

let genChartInstance, flowChartInstance, historyChartInstance, carbonChartInstance, fuelDetailChartInstance, fourDemandChartInstance;
let sparkDemand, sparkGen, sparkFlow, sparkFreq, sparkPrice, sparkMiPrice, sparkNiv, sparkCarbon, sparkPwLoad, sparkPwSolar, sparkPwBatt, sparkPwGrid, sparkOctImp, sparkOctExp;
let chartPwLoad, chartPwSolar, chartPwBatt, chartPwGrid, chartPriceDetailInstance, chartOctoDetailInstance;
let chartFreqDetailInstance, chartNivDetailInstance;
let forecastTempChart, forecastSolarChart, forecastRainChart, forecastWindChart;

let historyMode = 'GW', forecastMode = 24, powerUnit = 'kW', interconnectorMode = 'GW';
let isNivOverlayActive = false;
let cachedHistoryData = [], rawForecastData = null, currentGridData = null, currentTotalGW = 0;
let userGlowPref = true;
let activeConfig = null;
let currentSelectedFuel = 'solar';

document.getElementById('custom-fuel-selector-btn').addEventListener('click', function(event) {
    document.getElementById('custom-fuel-options').classList.toggle('hidden');
});

function selectFuel(val, label) {
    currentSelectedFuel = val;
    document.getElementById('custom-fuel-label').innerText = label;
    document.getElementById('custom-fuel-options').classList.add('hidden');
    updateFuelDetailChart();
}

function openInfoModal(fuelName) {
    document.getElementById('modal-title').innerText = fuelName;
    document.getElementById('modal-desc').innerHTML = fuelInfoText[fuelName] || "Information not available for this fuel type.";
    document.getElementById('info-modal').classList.remove('hidden');
}

function openMapModal() {
    document.getElementById('map-modal').classList.remove('hidden');
}

function openInterconnectorModal() {
    document.getElementById('modal-title').innerText = "Interconnector Capacities";
    let htmlList = `<ul class="space-y-2 mt-2">`;
    for (const [name, cap] of Object.entries(interconnectorCaps)) {
        htmlList += `<li><strong class="text-white">${name}:</strong> ${cap.toFixed(1)} GW Maximum Capacity</li>`;
    }
    htmlList += `</ul>`;
    document.getElementById('modal-desc').innerHTML = htmlList;
    document.getElementById('info-modal').classList.remove('hidden');
}

function togglePwCharts() {
    const el = document.getElementById('pw-expanded-charts');
    el.classList.toggle('hidden');
    if(!el.classList.contains('hidden')) {
        if(chartPwLoad) chartPwLoad.resize();
        if(chartPwSolar) chartPwSolar.resize();
        if(chartPwBatt) chartPwBatt.resize();
        if(chartPwGrid) chartPwGrid.resize();
    }
}

function toggleOctoCharts() {
    const el = document.getElementById('octo-expanded-chart');
    el.classList.toggle('hidden');
    if(!el.classList.contains('hidden') && chartOctoDetailInstance) chartOctoDetailInstance.resize();
}

function togglePriceCharts() {
    const el = document.getElementById('price-expanded-chart');
    el.classList.toggle('hidden');
    if(!el.classList.contains('hidden') && chartPriceDetailInstance) chartPriceDetailInstance.resize();
}

function toggleFreqChart() {
    const el = document.getElementById('freq-expanded-chart');
    el.classList.toggle('hidden');
    if(!el.classList.contains('hidden') && chartFreqDetailInstance) {
        chartFreqDetailInstance.resize();
    }
}

function toggleNivChart() {
    const el = document.getElementById('niv-expanded-chart');
    el.classList.toggle('hidden');
    if(!el.classList.contains('hidden') && chartNivDetailInstance) {
        chartNivDetailInstance.resize();
    }
}

function toggleNivOverlay() {
    isNivOverlayActive = !isNivOverlayActive;
    const btn = document.getElementById('btn-niv-overlay');
    if (isNivOverlayActive) {
        btn.classList.add('bg-white', 'text-ui-darkest', 'border-white');
        btn.classList.remove('bg-ui-dark', 'text-white', 'border-ui-grey');
    } else {
        btn.classList.remove('bg-white', 'text-ui-darkest', 'border-white');
        btn.classList.add('bg-ui-dark', 'text-white', 'border-ui-grey');
    }
    if (currentGridData) renderDashboardData(currentGridData); 
}

function smoothData(dataArray, windowSize = 9) {
    let smoothed = [];
    for (let i = 0; i < dataArray.length; i++) {
        let start = Math.max(0, i - Math.floor(windowSize / 2)), end = Math.min(dataArray.length, i + Math.floor(windowSize / 2) + 1), sum = 0;
        for (let j = start; j < end; j++) { sum += dataArray[j]; }
        smoothed.push(sum / (end - start));
    }
    return smoothed;
}

const centerTextPlugin = {
    id: 'centerText',
    beforeDraw: function(chart) {
        if (chart.config.type !== 'doughnut') return;
        const ctx = chart.ctx; ctx.save();
        ctx.font = 'bold 46px Inter'; ctx.fillStyle = '#FFFFFF'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        const centerX = (chart.chartArea.left + chart.chartArea.right) / 2, centerY = (chart.chartArea.top + chart.chartArea.bottom) / 2;
        ctx.fillText(currentTotalGW + " GW", centerX, centerY); ctx.restore();
    }
};
Chart.register(centerTextPlugin);

const formatPower = (w) => powerUnit === 'kW' ? (w / 1000).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : Math.round(w).toLocaleString();

function hexToRgbChannels(hex) {
    hex = hex.replace(/^#/, '');
    let bigint = parseInt(hex, 16);
    return `${(bigint >> 16) & 255} ${(bigint >> 8) & 255} ${bigint & 255}`;
}

function hexToRgbObj(hex) {
    hex = hex.replace(/^#/, '');
    let bigint = parseInt(hex, 16);
    return { r: (bigint >> 16) & 255, g: (bigint >> 8) & 255, b: bigint & 255 };
}

let tooltipTimeout;
function showCustomTooltip(e, htmlContent) {
    const tooltip = document.getElementById('custom-tooltip');
    tooltip.innerHTML = htmlContent;
    tooltip.classList.remove('hidden');
    clearTimeout(tooltipTimeout);
    setTimeout(() => tooltip.classList.remove('opacity-0'), 10);
    moveCustomTooltip(e);
}
function moveCustomTooltip(e) {
    const tooltip = document.getElementById('custom-tooltip');
    let x = e.clientX + 15; let y = e.clientY + 15;
    // Prevent it from clipping off the right/bottom edge of the screen
    if (x + tooltip.offsetWidth > window.innerWidth) x = e.clientX - tooltip.offsetWidth - 15;
    if (y + tooltip.offsetHeight > window.innerHeight) y = e.clientY - tooltip.offsetHeight - 15;
    tooltip.style.left = x + 'px'; tooltip.style.top = y + 'px';
}
function hideCustomTooltip() {
    const tooltip = document.getElementById('custom-tooltip');
    tooltip.classList.add('opacity-0');
    tooltipTimeout = setTimeout(() => tooltip.classList.add('hidden'), 200);
}

function applyConfig(config) {
    activeConfig = config;
    const root = document.documentElement;
    
    root.style.setProperty('--brand-cyan', hexToRgbChannels(config.theme.brand_cyan));
    root.style.setProperty('--brand-orange', hexToRgbChannels(config.theme.brand_orange));
    root.style.setProperty('--octo-pink', hexToRgbChannels(config.theme.octo_pink));
    root.style.setProperty('--tesla-green', hexToRgbChannels(config.theme.tesla_green));
    root.style.setProperty('--solar-yellow', hexToRgbChannels(config.fuels.solar));
    root.style.setProperty('--wind-green', hexToRgbChannels(config.fuels.wind));
 //   root.style.setProperty('--color-lv-wind', config.fuels.lv_wind);
    root.style.setProperty('--color-lv-wind', config.fuels.lv_wind || '#5FB035');
    root.style.setProperty('--hydro-blue', hexToRgbChannels(config.fuels.hydro));

    root.style.setProperty('--color-imports', config.fuels.imports);
    root.style.setProperty('--color-solar', config.fuels.solar);
    root.style.setProperty('--color-wind', config.fuels.wind);

    if(config.flow) {
        root.style.setProperty('--color-hv', config.flow.hv_gen);
        root.style.setProperty('--color-tot', config.flow.total);
        root.style.setProperty('--color-stor', config.flow.storage);
        root.style.setProperty('--color-flow-dem', config.flow.demand);
        root.style.setProperty('--color-flow-exp', config.flow.exports);
        root.style.setProperty('--color-flow-bg', config.flow.bg_color || '#000000');

        document.querySelectorAll('#flow-diagram .flow-dot').forEach(el => {
            el.setAttribute('r', config.flow.dot_size || 2.5);
        });

        if(config.flow.icons) {
            const applyIcon = (id, rawClass) => {
                const el = document.getElementById(id);
                if (el) {
                    el.className = getValidIcon(rawClass) + ' text-[18px]';
                }
            };
            applyIcon('icon-sol', config.flow.icons.sol);
            applyIcon('icon-imp', config.flow.icons.imp);
            applyIcon('icon-hv', config.flow.icons.hv);
            applyIcon('icon-wind', config.flow.icons.wind);
            applyIcon('icon-psh', config.flow.icons.psh);
            applyIcon('icon-dem', config.flow.icons.dem);
            applyIcon('icon-exp', config.flow.icons.exp);
        }
    }

    if (config.map_nodes) {
        const setNode = (key) => {
            const n = config.map_nodes[key];
            const g = document.getElementById('mg-' + key);
            if (g && n) g.setAttribute('transform', `translate(${n.x}, ${n.y})`);
        };
        ['uk','ire','fra','bel','ned','den','nor'].forEach(setNode);

        const setLine = (key) => {
            const n = config.map_nodes[key];
            const uk = config.map_nodes.uk;
            const l = document.getElementById('ml-' + key);
            if (l && n && uk) l.setAttribute('d', `M ${uk.x} ${uk.y} L ${n.x} ${n.y}`);
        };
        ['ire','fra','bel','ned','den','nor'].forEach(setLine);
    }

    let teslaRgbCommas = hexToRgbChannels(config.theme.tesla_green).replace(/ /g, ', ');
    let glowStyle = document.getElementById('dynamic-glow-style');
    if (!glowStyle) {
        glowStyle = document.createElement('style');
        glowStyle.id = 'dynamic-glow-style';
        document.head.appendChild(glowStyle);
    }
    glowStyle.innerHTML = `
        @keyframes tesla-glow {
            0%, 100% { box-shadow: 0 0 10px rgba(${teslaRgbCommas}, 0.2); border-color: rgba(${teslaRgbCommas}, 0.4); }
            50% { box-shadow: 0 0 25px rgba(${teslaRgbCommas}, 0.8); border-color: rgba(${teslaRgbCommas}, 1); }
        }
        .glow-tesla {
            animation: tesla-glow 2.5s ease-in-out infinite;
        }
    `;
    
    document.getElementById('lbl-nat').style.color = config.demand.national;
    document.getElementById('brk-nat').style.color = config.demand.national;
    document.getElementById('lbl-net').style.color = config.demand.net;
    document.getElementById('brk-net').style.color = config.demand.net;
    document.getElementById('lbl-gro').style.color = config.demand.gross;
    document.getElementById('brk-gro').style.color = config.demand.gross;

    const f = config.footer;
    const updateLink = (id, text, url) => {
        let el = document.getElementById(id);
        if(text && url) { el.innerText = text; el.href = url; el.classList.remove('hidden'); }
        else { el.classList.add('hidden'); }
    };
    updateLink('link-use-1', f.use1_text, f.use1_url);
    updateLink('link-use-2', f.use2_text, f.use2_url);
    updateLink('link-use-3', f.use3_text, f.use3_url);
    updateLink('link-use-4', f.use4_text, f.use4_url);
    updateLink('link-fol-1', f.fol1_text, f.fol1_url);
    updateLink('link-fol-2', f.fol2_text, f.fol2_url);
    updateLink('link-fol-3', f.fol3_text, f.fol3_url);
}

function getPriceColorRgb(p, config) {
    const interp = (c1, c2, f) => ({
        r: Math.round(c1.r + f * (c2.r - c1.r)),
        g: Math.round(c1.g + f * (c2.g - c1.g)),
        b: Math.round(c1.b + f * (c2.b - c1.b))
    });
    
    let low = config.thresh_low;
    let high = config.thresh_high;
    let mid = (low + high) / 2;
    
    if (p <= low) return hexToRgbObj(config.color_low);
    if (p >= high) return hexToRgbObj(config.color_high);
    
    if (p < mid) {
        return interp(hexToRgbObj(config.color_low), hexToRgbObj(config.color_med), (p - low) / (mid - low));
    } else {
        return interp(hexToRgbObj(config.color_med), hexToRgbObj(config.color_high), (p - mid) / (high - mid));
    }
}

function setPowerUnit(unit) {
    powerUnit = unit;
    document.getElementById('btn-kw').className = unit === 'kW' ? "px-5 py-1.5 rounded-full bg-ui-grey text-white font-semibold shadow-sm transition-all" : "px-5 py-1.5 rounded-full text-ui-light hover:text-white transition-all";
    document.getElementById('btn-w').className = unit === 'W' ? "px-5 py-1.5 rounded-full bg-ui-grey text-white font-semibold shadow-sm transition-all" : "px-5 py-1.5 rounded-full text-ui-light hover:text-white transition-all";
    document.querySelectorAll('.pw-unit-pill').forEach(el => el.innerText = unit);
    document.getElementById('title-chart-load').innerText = `Home Load (${unit})`;
    document.getElementById('title-chart-solar').innerText = `Solar Generated (${unit})`;
    document.getElementById('title-chart-grid').innerText = `Grid Flow (${unit})`;
    if (currentGridData && activeConfig) renderDashboardData(currentGridData);
}

function setInterconnectorMode(mode) {
    interconnectorMode = mode;
    document.getElementById('btn-ic-gw').className = mode === 'GW' ? "px-3 py-1 rounded bg-ui-grey text-white font-semibold transition" : "px-3 py-1 rounded text-ui-light hover:text-white transition";
    document.getElementById('btn-ic-perc').className = mode === '%' ? "px-3 py-1 rounded bg-ui-grey text-white font-semibold transition" : "px-3 py-1 rounded text-ui-light hover:text-white transition";
    if (currentGridData && activeConfig) renderDashboardData(currentGridData);
}

function setHistoryMode(mode) {
    historyMode = mode;
    document.getElementById('btn-gw').className = mode === 'GW' ? "px-4 py-1 rounded bg-ui-grey text-white font-semibold transition" : "px-4 py-1 rounded text-ui-light hover:text-white transition";
    document.getElementById('btn-perc').className = mode === '%' ? "px-4 py-1 rounded bg-ui-grey text-white font-semibold transition" : "px-4 py-1 rounded text-ui-light hover:text-white transition";
    if (currentGridData && activeConfig) renderDashboardData(currentGridData);
}

function toggleForecasts() {
    const chartDivs = document.querySelectorAll('.weather-expanded-charts');
    const pill = document.getElementById('forecast-toggle-pill');
    chartDivs.forEach(div => div.classList.toggle('hidden'));
    pill.classList.toggle('hidden');
}

function toggleGlow() {
    userGlowPref = !userGlowPref;
    if (currentGridData) applyGlowLogic(currentGridData);
}

function applyGlowLogic(data) {
    const card = document.getElementById('home-card');
    const btn = document.getElementById('btn-glow');
    const batteryFlowing = Math.abs(data.powerwall.battery_w) > 20;

    if (batteryFlowing) {
        btn.classList.remove('hidden');
        if (userGlowPref) card.classList.add('glow-tesla');
        else card.classList.remove('glow-tesla');
    } else {
        btn.classList.add('hidden');
        card.classList.remove('glow-tesla');
    }
}

function setForecastMode(hours) {
    forecastMode = hours;
    document.getElementById('btn-24h').className = hours === 24 ? "px-5 py-1.5 rounded-full bg-ui-grey text-white font-semibold shadow-sm transition-all" : "px-5 py-1.5 rounded-full text-ui-light hover:text-white transition-all";
    document.getElementById('btn-7d').className = hours === 168 ? "px-5 py-1.5 rounded-full bg-ui-grey text-white font-semibold shadow-sm transition-all" : "px-5 py-1.5 rounded-full text-ui-light hover:text-white transition-all";
    if (activeConfig) renderForecastCharts();
}

function buildSparkline(instance, ctxId, dataArray, timeLabels, colorStr, bgStr, fixedMin = null, fixedMax = null) {
    if (instance) { 
        instance.data.labels = timeLabels; 
        instance.data.datasets[0].data = dataArray; 
        instance.data.datasets[0].borderColor = colorStr; 
        instance.data.datasets[0].backgroundColor = bgStr; 
        instance.update(); 
        return instance; 
    }
    const options = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { display: false } }, animation: false, layout: { padding: { top: 10 } } };
    if (fixedMin !== null) options.scales.y.min = fixedMin;
    if (fixedMax !== null) options.scales.y.max = fixedMax;
    return new Chart(document.getElementById(ctxId).getContext('2d'), { type: 'line', data: { labels: timeLabels, datasets: [{ data: dataArray, borderColor: colorStr, backgroundColor: bgStr, fill: true, borderWidth: 2, pointRadius: 0, tension: 0.4 }] }, options: options });
}

function buildFullChart(instance, ctxId, dataArray, timeLabels, borderCol, bgCol, showX = false, fixedMin = null, fixedMax = null) {
    if (instance) { instance.data.labels = timeLabels; instance.data.datasets[0].data = dataArray; instance.data.datasets[0].borderColor = borderCol; instance.data.datasets[0].backgroundColor = bgCol; instance.options.scales.x.display = showX; instance.update(); return instance; }
    const options = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { display: showX, grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 8 } }, y: { grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA' } } } };
    if (fixedMin !== null) options.scales.y.min = fixedMin;
    if (fixedMax !== null) options.scales.y.max = fixedMax;
    return new Chart(document.getElementById(ctxId).getContext('2d'), { type: 'line', data: { labels: timeLabels, datasets: [{ data: dataArray, borderColor: borderCol, backgroundColor: bgCol, fill: true, borderWidth: 2, pointRadius: 0, tension: 0.3 }] }, options: options });
}

function updateFuelDetailChart() {
    if(!cachedHistoryData.length || !activeConfig) return;
    const timeLabels = cachedHistoryData.map(h => new Date(h.time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}));
    
    const rawData = cachedHistoryData.map(h => {
        const f = h.mix.find(x => x.fuel === currentSelectedFuel);
        return f ? f.mw / 1000 : 0;
    });
    const dataArray = smoothData(rawData, 9);
    
    const colorStr = activeConfig.fuels[currentSelectedFuel];
    let rgb = hexToRgbChannels(colorStr).replace(/ /g, ',');
    const bgStr = `rgba(${rgb}, 0.2)`;

    fuelDetailChartInstance = buildFullChart(fuelDetailChartInstance, 'fuelDetailChart', dataArray, timeLabels, colorStr, bgStr, true);
}

function renderHistoryChart() {
    if(!cachedHistoryData.length || !activeConfig) return;
    const timeLabels = cachedHistoryData.map(h => new Date(h.time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}));
    const apiFuels = ["nuclear", "ccgt", "ocg", "other", "imports", "biomass", "pumped_storage", "hydro", "solar", "lv_wind", "wind"];
    const historyColours = { "wind": activeConfig.fuels.wind, "lv_wind": activeConfig.fuels.lv_wind || '#5FB035', "solar": activeConfig.fuels.solar, "hydro": activeConfig.fuels.hydro, "pumped_storage": activeConfig.fuels.pumped_storage, "biomass": activeConfig.fuels.biomass, "nuclear": activeConfig.fuels.nuclear, "imports": activeConfig.fuels.imports, "other": activeConfig.fuels.other, "ocg": activeConfig.fuels.ocg, "ccgt": activeConfig.fuels.ccgt };
    
    let datasets = apiFuels.map(fuel => ({
        type: 'line', label: fuel.toUpperCase(),
        data: smoothData(cachedHistoryData.map(h => { 
            const f = h.mix.find(x => x.fuel === fuel);
            if (!f) return 0;
            return historyMode === 'GW' ? f.mw / 1000 : f.perc; 
        }), 9), 
        backgroundColor: historyColours[fuel], borderColor: 'transparent', fill: true, pointRadius: 0, tension: 0.4, stack: 'generation', order: 1
    }));
    
    if (historyMode === 'GW') {
        datasets.push({
            type: 'line', label: 'Grid Demand',
            data: smoothData(cachedHistoryData.map(h => h.demand_mw / 1000), 9),
            borderColor: activeConfig.demand.dashed, borderWidth: 2, borderDash: [5, 5],
            backgroundColor: 'transparent', fill: false, pointRadius: 0, tension: 0.4, stack: 'demand', order: 0
        });
    }
    
    if(historyChartInstance) { 
        historyChartInstance.data.labels = timeLabels; historyChartInstance.data.datasets = datasets; 
        if (historyMode === '%') { historyChartInstance.options.scales.y.max = 100; } else { delete historyChartInstance.options.scales.y.max; }
        historyChartInstance.update(); 
    } else { 
        historyChartInstance = new Chart(document.getElementById('historyChart').getContext('2d'), { type: 'line', data: { labels: timeLabels, datasets: datasets }, options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { stacked: true, min: 0, grid: { color: '#3F3F46' } } } } }); 
    }
}

function renderForecastCharts() {
    if(!rawForecastData || !activeConfig) return;
    const now = new Date();
    const currentHourIdx = rawForecastData.hourly.time.findIndex(t => new Date(t) > now) - 1;
    const idx = currentHourIdx > 0 ? currentHourIdx : 0;
    
    document.getElementById('w-rain').innerText = rawForecastData.hourly.precipitation_probability[idx];

    const sliceLen = forecastMode;
    const timeLabels = rawForecastData.hourly.time.slice(idx, idx + sliceLen).map(t => {
        const d = new Date(t);
        return forecastMode === 24 ? d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : d.toLocaleDateString([], {weekday: 'short', hour: '2-digit'});
    });
    
    const tCtx = document.getElementById('chartForecastTemp').getContext('2d');
    const tGrad = tCtx.createLinearGradient(0, 0, 0, 200); 
    tGrad.addColorStop(0, activeConfig.gradients.temp_hot); 
    tGrad.addColorStop(1, activeConfig.gradients.temp_cold);
    
    let hotRgb = hexToRgbChannels(activeConfig.gradients.temp_hot).replace(/ /g, ',');
    let coldRgb = hexToRgbChannels(activeConfig.gradients.temp_cold).replace(/ /g, ',');
    const tBg = tCtx.createLinearGradient(0, 0, 0, 200); 
    tBg.addColorStop(0, `rgba(${hotRgb}, 0.2)`); 
    tBg.addColorStop(1, `rgba(${coldRgb}, 0.2)`);

    let yellowRgb = hexToRgbChannels(activeConfig.fuels.solar).replace(/ /g, ',');
    let blueRgb = hexToRgbChannels(activeConfig.fuels.hydro).replace(/ /g, ',');
    let greenRgb = hexToRgbChannels(activeConfig.fuels.wind).replace(/ /g, ',');

    forecastTempChart = buildFullChart(forecastTempChart, 'chartForecastTemp', rawForecastData.hourly.temperature_2m.slice(idx, idx + sliceLen), timeLabels, tGrad, tBg, true, 0, 40);
    forecastSolarChart = buildFullChart(forecastSolarChart, 'chartForecastSolar', rawForecastData.hourly.direct_normal_irradiance.slice(idx, idx + sliceLen), timeLabels, activeConfig.fuels.solar, `rgba(${yellowRgb}, 0.2)`, true);
    forecastRainChart = buildFullChart(forecastRainChart, 'chartForecastRain', rawForecastData.hourly.precipitation_probability.slice(idx, idx + sliceLen), timeLabels, activeConfig.fuels.hydro, `rgba(${blueRgb}, 0.2)`, true, 0, 100);
    forecastWindChart = buildFullChart(forecastWindChart, 'chartForecastWind', rawForecastData.hourly.wind_speed_10m.slice(idx, idx + sliceLen), timeLabels, activeConfig.fuels.wind, `rgba(${greenRgb}, 0.2)`, true);
}

function fetchWeatherForecast() {
    fetch('/static/forecast.json') // <-- Replaced URL here
    .then(res => res.json())
    .then(data => { rawForecastData = data; renderForecastCharts(); })
    .catch(e => console.error("Forecast fetch failed:", e)); // Added error handling just in case
}

function setFlowSpeed(idPrefix, gwValue) {
    const anim1 = document.getElementById(`anim-${idPrefix}-1`);
    const anim2 = document.getElementById(`anim-${idPrefix}-2`);
    const dot1 = document.getElementById(`dot-${idPrefix}-1`);
    const dot2 = document.getElementById(`dot-${idPrefix}-2`);
    
    if (!anim1 || !dot1) return;

    if (gwValue <= 0.005) {
        dot1.style.display = 'none';
        dot2.style.display = 'none';
        return;
    }

    dot1.style.display = 'block';
    dot2.style.display = 'block';

    const mode = activeConfig.flow?.speed_mode || 'relative';
    const baseSpeed = activeConfig.flow?.base_speed || 5;
    
    let dur;
    if (mode === 'uniform') {
        dur = 25.0 / baseSpeed;
    } else {
        dur = (40 / baseSpeed) / Math.sqrt(Math.max(gwValue, 0.1));
        dur = Math.max(1.0, Math.min(30, dur));
    }

    anim1.setAttribute('dur', dur + 's');
    anim2.setAttribute('dur', dur + 's');
    anim2.setAttribute('begin', (dur / 2) + 's');
}

function updateDashboard() {
    Promise.all([
        fetch('/api/config').then(res => res.json()),
        fetch('/api/data').then(res => res.json()),
        fetch('/static/forecast.json').then(res => res.json()) // <-- Replaced URL here
    ]).then(([configData, gridData, weatherData]) => {
        applyConfig(configData);
        rawForecastData = weatherData;
        currentGridData = gridData;
        renderDashboardData(gridData);
        renderForecastCharts();
    }).catch(e => console.error("Update failed:", e));
}

function renderDashboardData(data) {
    document.getElementById('update-time').innerText = "Last updated: " + new Date().toLocaleTimeString();
    document.getElementById('cf-visits').innerText = data.cloudflare && data.cloudflare.visits ? data.cloudflare.visits.toLocaleString() : '--';

    let eff = (activeConfig.powerwall && activeConfig.powerwall.solar_efficiency) ? activeConfig.powerwall.solar_efficiency : 95.5;
    let dc_multiplier = eff / 100;

    document.getElementById('w-temp').innerText = data.weather.temp_c;
    document.getElementById('w-wind').innerText = data.weather.wind_mph.toFixed(1);
    const hrs = Math.floor(data.weather.daylight_secs / 3600), mins = Math.floor((data.weather.daylight_secs % 3600) / 60);
    document.getElementById('w-daylight').innerText = `${hrs}h ${mins}m`;

    document.getElementById('demand-val').innerText = formatGW(data.demand_mw);
    document.getElementById('gen-val').innerText = formatGW(data.total_generation_mw);
    document.getElementById('net-flow-val').innerText = formatGW(Math.abs(data.net_flow_mw));
    document.getElementById('freq-val').innerText = data.grid_frequency.toFixed(3);
    
    const rawIntensity = data.carbon_history.map(h => h.intensity);
    const latestCarbon = data.carbon_intensity;
    const intensityEl = document.getElementById('intensity-val');
    const carbonCard = document.getElementById('carbon-card');
    
    intensityEl.innerText = latestCarbon;
    
    let ragColor, ragBg;
    if (latestCarbon < 100) { ragColor = activeConfig.carbon.low; } 
    else if (latestCarbon < 200) { ragColor = activeConfig.carbon.med; } 
    else { ragColor = activeConfig.carbon.high; }
    ragBg = `rgba(${hexToRgbChannels(ragColor).replace(/ /g, ',')}, 0.2)`;
    carbonCard.style.borderColor = ragColor;
    intensityEl.style.color = ragColor;
    
    let priceValObj = getPriceColorRgb(data.wholesale_price, activeConfig.price);
    let priceColorStr = `rgb(${priceValObj.r}, ${priceValObj.g}, ${priceValObj.b})`;
    document.getElementById('price-val').innerText = data.wholesale_price < 0 ? `-£${Math.abs(data.wholesale_price).toFixed(2)}` : `£${data.wholesale_price.toFixed(2)}`;
    document.getElementById('price-val').style.color = priceColorStr;
    document.getElementById('price-title').style.color = priceColorStr;
    document.getElementById('price-card').style.borderColor = priceColorStr;

    let nivVal = data.net_imbalance_volume || 0;
    document.getElementById('niv-val').innerText = nivVal > 0 ? `+${nivVal.toLocaleString()}` : nivVal.toLocaleString();
    let nivColor = nivVal > 0 ? (activeConfig.niv?.color_short || activeConfig.theme.brand_orange) : (activeConfig.niv?.color_long || activeConfig.theme.brand_cyan);
    let nivRgb = hexToRgbChannels(nivColor).replace(/ /g, ',');
    document.getElementById('niv-val').style.color = nivColor;
    document.getElementById('niv-card').style.borderColor = nivColor;

    let miPriceValObj = getPriceColorRgb(data.market_index_price, activeConfig.mi_price);
    let miPriceColorStr = `rgb(${miPriceValObj.r}, ${miPriceValObj.g}, ${miPriceValObj.b})`;
    document.getElementById('mi-price-val').innerText = data.market_index_price < 0 ? `-£${Math.abs(data.market_index_price).toFixed(2)}` : `£${data.market_index_price.toFixed(2)}`;
    document.getElementById('mi-price-val').style.color = miPriceColorStr;
    document.getElementById('mi-price-title').style.color = miPriceColorStr;
    document.getElementById('mi-price-card').style.borderColor = miPriceColorStr;

    document.getElementById('pw-home').innerText = formatPower(data.powerwall.home_w);
    
    let live_solar_w = Math.max(0, data.powerwall.solar_w);
    document.getElementById('pw-solar').innerText = formatPower(live_solar_w);
    
    const solLabel = document.getElementById('pw-solar-label');
    if (live_solar_w > 20) {
        solLabel.innerText = `DC Est: ${formatPower(live_solar_w / dc_multiplier)} ${powerUnit}`;
        solLabel.className = "text-xs text-[#A1A1AA] font-medium mt-1";
    } else {
        solLabel.innerText = "Idle";
        solLabel.className = "text-xs text-[#A1A1AA] font-medium mt-1";
    }
    
    document.getElementById('pw-level').innerText = data.powerwall.level !== null ? appBatteryLevel(data.powerwall.level).toFixed(1) : '---';
    
    const batW = data.powerwall.battery_w, batLabel = document.getElementById('pw-battery-label');
    if (batW > 20) { batLabel.innerText = `Discharging ${formatPower(batW)} ${powerUnit}`; batLabel.className = "text-xs text-[#A1A1AA] font-medium mt-1"; } 
    else if (batW < -20) { batLabel.innerText = `Charging ${formatPower(Math.abs(batW))} ${powerUnit}`; batLabel.className = "text-xs text-[#A1A1AA] font-medium mt-1"; } 
    else { batLabel.innerText = "Idle"; batLabel.className = "text-xs text-[#A1A1AA] font-medium mt-1"; }

    const gridW = data.powerwall.grid_w; document.getElementById('pw-grid').innerText = formatPower(Math.abs(gridW));
    if(gridW > 20) { document.getElementById('pw-grid').className = "text-5xl xl:text-6xl font-extrabold text-brand-orange mt-1"; document.getElementById('pw-grid-label').innerText = "Importing from Grid"; } else if (gridW < -20) { document.getElementById('pw-grid').className = "text-5xl xl:text-6xl font-extrabold text-brand-cyan mt-1"; document.getElementById('pw-grid-label').innerText = "Exporting to Grid"; } else { document.getElementById('pw-grid').className = "text-5xl xl:text-6xl font-extrabold text-white mt-1"; document.getElementById('pw-grid-label').innerText = "Idle"; }

    const gridBadge = document.getElementById('grid-status-badge');
    if (data.powerwall.grid_status === "UP") { gridBadge.innerText = "UP"; gridBadge.className = "text-xs px-2 py-1 rounded bg-[#166534] text-[#4ADE80] font-mono tracking-widest shadow-sm"; } else { gridBadge.innerText = "DOWN"; gridBadge.className = "text-xs px-2 py-1 rounded bg-brand-orange text-white font-bold tracking-widest animate-pulse shadow-sm"; }

    // --- NEW: Weather API Status Badge ---
    const weatherBadge = document.getElementById('weather-status-badge');
    if (data.weather.status === "UP") { 
        weatherBadge.innerText = "UP"; 
        weatherBadge.className = "text-xs px-2 py-1 rounded bg-[#166534] text-[#4ADE80] font-mono tracking-widest shadow-sm"; 
    } else { 
        weatherBadge.innerText = "DOWN"; 
        weatherBadge.className = "text-xs px-2 py-1 rounded bg-brand-orange text-white font-bold tracking-widest animate-pulse shadow-sm"; 
    }

    applyGlowLogic(data);

    let cum_solar_dc = data.powerwall.cum_solar_kwh / dc_multiplier;

    document.getElementById('cum-home').innerText = `Today: ${data.powerwall.cum_home_kwh.toFixed(1)} kWh`;
    document.getElementById('cum-solar').innerHTML = `Today AC: ${data.powerwall.cum_solar_kwh.toFixed(1)} kWh<br><span class="text-[#A1A1AA]">DC Est: ${cum_solar_dc.toFixed(1)} kWh</span>`;
    document.getElementById('cum-batt').innerHTML = `In: ${data.powerwall.cum_batt_chg_kwh.toFixed(1)} kWh<br>Out: ${data.powerwall.cum_batt_dischg_kwh.toFixed(1)} kWh`;
    document.getElementById('cum-grid').innerHTML = `Imp: ${data.powerwall.cum_grid_import_kwh.toFixed(1)} kWh<br>Exp: ${data.powerwall.cum_grid_export_kwh.toFixed(1)} kWh`;

    document.getElementById('oct-imp-val').innerText = data.octopus.import_pence.toFixed(1);
    document.getElementById('oct-exp-val').innerText = data.octopus.export_pence.toFixed(1);
    document.getElementById('oct-yest-imp').innerText = data.octopus.yest_import_kwh.toFixed(1);
    document.getElementById('oct-yest-exp').innerText = data.octopus.yest_export_kwh.toFixed(1);
    document.getElementById('oct-yest-gas').innerText = data.octopus.yest_gas_kwh.toFixed(1);
    document.getElementById('oct-yest-gas-m3').innerText = data.octopus.yest_gas_m3.toFixed(1) + ' m³';

    const octoDate = data.octopus.yest_date ? ` (${data.octopus.yest_date})` : '';
    document.getElementById('title-oct-imp').innerText = `Elec Import${octoDate}`;
    document.getElementById('title-oct-exp').innerText = `Elec Export${octoDate}`;
    document.getElementById('title-oct-gas').innerText = `Gas Used${octoDate}`;

    const flowInd = document.getElementById('flow-indicator');
    if (data.net_flow_mw > 0) { flowInd.innerText = "↓"; flowInd.className = "w-10 h-10 flex-shrink-0 flex items-center justify-center bg-brand-orange text-ui-darkest rounded-full font-black text-xl z-10 pointer-events-auto"; } else { flowInd.innerText = "↑"; flowInd.className = "w-10 h-10 flex-shrink-0 flex items-center justify-center bg-brand-cyan text-ui-darkest rounded-full font-black text-xl z-10 pointer-events-auto"; }

    currentTotalGW = formatGW(data.total_generation_mw); 
    
    const fuelColours = { "CCGT": activeConfig.fuels.ccgt, "OCG": activeConfig.fuels.ocg, "Wind": activeConfig.fuels.wind, "LV Wind": activeConfig.fuels.lv_wind || '#5FB035', "Nuclear": activeConfig.fuels.nuclear, "Biomass": activeConfig.fuels.biomass, "Hydro": activeConfig.fuels.hydro, "Pumped Storage": activeConfig.fuels.pumped_storage, "Solar": activeConfig.fuels.solar, "Other": activeConfig.fuels.other };
    const rawGenLabels = Object.keys(data.generation_mix);
    const sortedGenLabels = rawGenLabels.sort((a, b) => { let idxA = sortOrder.indexOf(a); let idxB = sortOrder.indexOf(b); if(idxA === -1) idxA = 99; if(idxB === -1) idxB = 99; return idxA - idxB; });
    const genValuesGW = sortedGenLabels.map(label => data.generation_mix[label] / 1000);
    const genBackgrounds = sortedGenLabels.map(fuel => fuelColours[fuel] || '#3F3F46');

    const legendContainer = document.getElementById('custom-legend'); legendContainer.innerHTML = '';
    sortedGenLabels.forEach((label, index) => {
        legendContainer.innerHTML += `<div class="flex items-center justify-between text-xs bg-ui-darkest/40 p-2 rounded-lg border border-ui-grey/20"><div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full shadow-sm" style="background-color: ${genBackgrounds[index]}"></span><span class="text-ui-light font-medium">${label}</span><button onclick="openInfoModal('${label}')" class="w-4 h-4 rounded-full bg-ui-grey/50 text-white flex items-center justify-center text-[9px] hover:text-ui-darkest transition font-bold cursor-pointer" style="hover:background-color:var(--brand-cyan);">i</button></div><span class="font-bold text-white">${genValuesGW[index].toFixed(2)} GW</span></div>`;
    });

    if(genChartInstance) { 
        genChartInstance.data.labels = sortedGenLabels; genChartInstance.data.datasets[0].data = genValuesGW; genChartInstance.data.datasets[0].backgroundColor = genBackgrounds; genChartInstance.update(); 
    } else { 
        genChartInstance = new Chart(document.getElementById('genMixChart').getContext('2d'), { 
            type: 'doughnut', data: { labels: sortedGenLabels, datasets: [{ data: genValuesGW, backgroundColor: genBackgrounds, borderColor: '#252529', borderWidth: 2 }] }, 
            options: { responsive: true, maintainAspectRatio: false, cutout: '70%', plugins: { legend: { display: false }, datalabels: { display: true, color: '#FFFFFF', font: { weight: 'bold', family: "'Inter', sans-serif", size: 14 }, formatter: (value, ctx) => { let sum = 0; let dataArr = ctx.chart.data.datasets[0].data; dataArr.map(data => { sum += data; }); let percentage = (value * 100 / sum).toFixed(1) + "%"; return (value * 100 / sum) > 3 ? percentage : null; } } } } 
        }); 
    }

    const flowLabels = data.interconnector_flows.map(i => i.name), flowValuesGW = data.interconnector_flows.map(i => i.flow / 1000), flowColors = flowValuesGW.map(flow => flow > 0 ? activeConfig.theme.brand_orange : activeConfig.theme.brand_cyan);
    if(flowChartInstance) { 
        flowChartInstance.data.labels = flowLabels; flowChartInstance.data.datasets[0].data = flowValuesGW; flowChartInstance.data.datasets[0].backgroundColor = flowColors; flowChartInstance.update(); 
    } else { 
        flowChartInstance = new Chart(document.getElementById('interconnectorChart').getContext('2d'), { 
            type: 'bar', data: { labels: flowLabels, datasets: [{ data: flowValuesGW, backgroundColor: flowColors, borderRadius: 5 }] }, 
            options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: function(ctx) { const val = ctx.raw; const cap = interconnectorCaps[ctx.label]; if(!cap) return val.toFixed(2) + ' GW'; return `${val.toFixed(2)} GW (${Math.abs(val / cap * 100).toFixed(0)}%)`; } } }, datalabels: { display: true, color: '#FFFFFF', font: { weight: 'normal', family: "'Inter', sans-serif", size: 12 }, anchor: 'center', align: 'center', formatter: (value, ctx) => { const label = ctx.chart.data.labels[ctx.dataIndex]; const cap = interconnectorCaps[label]; if(!cap) return value.toFixed(2) + ' GW'; return interconnectorMode === '%' ? Math.abs(value / cap * 100).toFixed(0) + '%' : value.toFixed(2) + ' GW'; } } }, scales: { x: { grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA' } }, y: { grid: { display: false }, ticks: { color: '#FFFFFF', font: { weight: 'bold' } } } } } 
        }); 
    }

    cachedHistoryData = data.history; 
    renderHistoryChart();
    updateFuelDetailChart();


 // FULL SECTION REPLACED WHEN ADDING LV WIND   
 //   const transArr = data.history.map(h => h.demand_mw / 1000);
 //   const embeddedArr = data.history.map(h => h.solar_mw / 1000);
 //   const exportArr = data.history.map(h => h.exports_mw / 1000);
 //   const pshArr = data.history.map(h => h.psh_pumping_mw / 1000);
 //   const statLd = 0.5;

    const transArr = data.history.map(h => h.transmission_mw / 1000);
    const embeddedArr = data.history.map(h => h.embedded_mw / 1000);

    const exportArr = data.history.map(h => h.exports_mw / 1000);
    const pshArr = data.history.map(h => h.psh_pumping_mw / 1000);
    const statLd = 0.5;

    const natArr = transArr.map((t, i) => t - exportArr[i] - pshArr[i] - statLd);
    const netArr = natArr.map((n, i) => n + embeddedArr[i]);
    const groArr = transArr.map((t, i) => t + embeddedArr[i]);

    document.getElementById('brk-trans').innerText = (data.breakdown.transmission_mw / 1000).toFixed(2);
    document.getElementById('brk-emb').innerText = (data.breakdown.embedded_mw / 1000).toFixed(2);
    document.getElementById('brk-exp').innerText = (data.breakdown.exports_mw / 1000).toFixed(2);
    document.getElementById('brk-psh').innerText = (data.breakdown.psh_pumping_mw / 1000).toFixed(2);
    const nNat = (data.breakdown.transmission_mw / 1000) - (data.breakdown.exports_mw / 1000) - (data.breakdown.psh_pumping_mw / 1000) - statLd;
    document.getElementById('brk-nat').innerText = nNat.toFixed(2);
    const nNet = nNat + (data.breakdown.embedded_mw / 1000);
    document.getElementById('brk-net').innerText = nNet.toFixed(2);
    document.getElementById('brk-gro').innerText = ((data.breakdown.transmission_mw / 1000) + (data.breakdown.embedded_mw / 1000)).toFixed(2);

    // --- FLOW DIAGRAM & MAP DATA UPDATE ---
    let flow_imp = 0;
    let flow_exp = 0;
    const mapFlows = { "France": 0, "Ireland": 0, "Netherlands": 0, "Belgium": 0, "Norway": 0, "Denmark": 0 };
    
    data.interconnector_flows.forEach(i => {
        if(i.flow > 0) flow_imp += i.flow;
        else flow_exp += Math.abs(i.flow);

        let country = i.name.split(' (')[0];
        if (mapFlows[country] !== undefined) { mapFlows[country] += i.flow / 1000; }
    });

    // Update Map DOM
    const updateMapCountry = (cKey, cName) => {
        let val = mapFlows[cName];
        let txtEl = document.getElementById('mt-' + cKey);
        let circEl = document.getElementById('mc-' + cKey);
        let lineEl = document.getElementById('ml-' + cKey);

        if (txtEl) txtEl.textContent = Math.abs(val).toFixed(2);
        
        let col = val > 0 ? activeConfig.fuels.imports : (val < 0 ? activeConfig.flow?.exports || '#FF00A0' : '#3F3F46');
        if (circEl) circEl.setAttribute('stroke', col);
        
        if (lineEl) {
            lineEl.setAttribute('stroke', col);
            
            if (Math.abs(val) > 0.005) {
                lineEl.classList.add('dash-flow');
                lineEl.classList.remove('anim-import', 'anim-export');
                lineEl.classList.add(val > 0 ? 'anim-import' : 'anim-export');
                
                const baseSpeed = activeConfig.flow?.base_speed || 5;
                let dur = (10 / baseSpeed) / Math.sqrt(Math.abs(val));
                dur = Math.max(0.5, Math.min(10, dur));
                lineEl.style.animationDuration = dur + 's';
            } else {
                lineEl.classList.remove('dash-flow', 'anim-import', 'anim-export');
            }
        }
    };
    
    updateMapCountry('ire', 'Ireland');
    updateMapCountry('fra', 'France');
    updateMapCountry('bel', 'Belgium');
    updateMapCountry('ned', 'Netherlands');
    updateMapCountry('den', 'Denmark');
    updateMapCountry('nor', 'Norway');
    
    const val_imp = flow_imp / 1000;
    const val_exp = flow_exp / 1000;
    const val_wind = (data.generation_mix['Wind'] || 0) / 1000;
    const val_lv_wind = (data.generation_mix['LV Wind'] || 0) / 1000;
    const val_sol = (data.generation_mix['Solar'] || 0) / 1000;
    const val_hv = (data.total_generation_mw / 1000) - val_wind - val_lv_wind - val_sol;
    const val_tot = (data.total_generation_mw + flow_imp) / 1000;
    const val_psh = (data.breakdown.psh_pumping_mw || 0) / 1000;
    const val_dem = nNet;

    document.getElementById('svg-val-imp').textContent = val_imp.toFixed(2) + ' GW';
    document.getElementById('svg-val-hv').textContent = Math.max(0, val_hv).toFixed(2) + ' GW';
 //   document.getElementById('svg-val-wind').textContent = val_wind.toFixed(2) + ' GW';
 //   document.getElementById('svg-val-lv-wind').textContent = val_lv_wind.toFixed(2) + ' GW';

// Calculate total wind and update the main node text
    const wind_total = val_wind + val_lv_wind;
    document.getElementById('svg-val-wind-total').textContent = wind_total.toFixed(2) + ' GW';
    
    // Update the hover tooltip
 //   document.getElementById('wind-hover-title').textContent = `Total Wind: ${wind_total.toFixed(2)} GW\nHV Wind: ${val_wind.toFixed(2)} GW\nLV Wind: ${val_lv_wind.toFixed(2)} GW`;
    
 
 // Setup rich tooltip interactions
    const windGroup = document.getElementById('wind-node-group');
    if (windGroup) {
        const tipHtml = `
            <div class="font-bold mb-1.5 border-b border-ui-grey/50 pb-1.5 text-[13px]">Total Wind: ${wind_total.toFixed(2)} GW</div>
            <div class="flex justify-between gap-6 mb-1">
                <span class="font-medium" style="color: ${activeConfig.fuels.wind}">HV Wind:</span> 
                <span class="font-mono font-bold">${val_wind.toFixed(2)} GW</span>
            </div>
            <div class="flex justify-between gap-6">
                <span class="font-medium" style="color: ${activeConfig.fuels.lv_wind || '#5FB035'}">LV Wind:</span> 
                <span class="font-mono font-bold">${val_lv_wind.toFixed(2)} GW</span>
            </div>
        `;
        windGroup.onmouseenter = (e) => showCustomTooltip(e, tipHtml);
        windGroup.onmousemove = moveCustomTooltip;
        windGroup.onmouseleave = hideCustomTooltip;
    }
 
// Setup HV Gen hover tooltip
    const hvGroup = document.getElementById('hv-node-group');
    if (hvGroup) {
        const mix = data.generation_mix;
        const gas = ((mix['CCGT'] || 0) + (mix['OCG'] || 0)) / 1000;
        const nuclear = (mix['Nuclear'] || 0) / 1000;
        const biomass = (mix['Biomass'] || 0) / 1000;
        const hydro = (mix['Hydro'] || 0) / 1000;
        
        // Only show pumped storage here if it is actively generating (> 0)
        const pshGen = Math.max(0, (mix['Pumped Storage'] || 0) / 1000);
        const other = (mix['Other'] || 0) / 1000;

        const tipHtml = `
            <div class="font-bold mb-1.5 border-b border-ui-grey/50 pb-1.5 text-[13px]">HV Gen Breakdown: ${Math.max(0, val_hv).toFixed(2)} GW</div>
            <div class="flex justify-between gap-6 mb-1">
                <span class="font-medium" style="color: ${activeConfig.fuels.ccgt}">Gas (CCGT/OCG):</span> 
                <span class="font-mono font-bold">${gas.toFixed(2)} GW</span>
            </div>
            <div class="flex justify-between gap-6 mb-1">
                <span class="font-medium" style="color: ${activeConfig.fuels.nuclear}">Nuclear:</span> 
                <span class="font-mono font-bold">${nuclear.toFixed(2)} GW</span>
            </div>
            <div class="flex justify-between gap-6 mb-1">
                <span class="font-medium" style="color: ${activeConfig.fuels.biomass}">Biomass:</span> 
                <span class="font-mono font-bold">${biomass.toFixed(2)} GW</span>
            </div>
            <div class="flex justify-between gap-6 mb-1">
                <span class="font-medium" style="color: ${activeConfig.fuels.hydro}">Hydro:</span> 
                <span class="font-mono font-bold">${hydro.toFixed(2)} GW</span>
            </div>
            <div class="flex justify-between gap-6 mb-1">
                <span class="font-medium" style="color: ${activeConfig.fuels.pumped_storage}">Pumped Storage:</span> 
                <span class="font-mono font-bold">${pshGen.toFixed(2)} GW</span>
            </div>
            <div class="flex justify-between gap-6">
                <span class="font-medium" style="color: ${activeConfig.fuels.other}">Other:</span> 
                <span class="font-mono font-bold">${other.toFixed(2)} GW</span>
            </div>
        `;
        hvGroup.onmouseenter = (e) => showCustomTooltip(e, tipHtml);
        hvGroup.onmousemove = moveCustomTooltip;
        hvGroup.onmouseleave = hideCustomTooltip;
    }
    // Calculate the math for the SVG donut chart
    const windPieCircumference = 2 * Math.PI * 46; // Math.PI * radius * 2
    const lvPercentage = wind_total > 0 ? (val_lv_wind / wind_total) : 0;
    const lvDash = lvPercentage * windPieCircumference;
    
    // Apply the pie chart segment size dynamically
    document.getElementById('svg-wind-pie').setAttribute('stroke-dasharray', `${lvDash} ${windPieCircumference}`);


    document.getElementById('svg-val-sol').textContent = val_sol.toFixed(2) + ' GW';
    document.getElementById('svg-val-tot').textContent = val_tot.toFixed(2) + ' GW';
    document.getElementById('svg-val-psh').textContent = val_psh.toFixed(2) + ' GW';
    document.getElementById('svg-val-dem').textContent = Math.max(0, val_dem).toFixed(2) + ' GW';
    document.getElementById('svg-val-exp').textContent = val_exp.toFixed(2) + ' GW';

    setFlowSpeed('imp', val_imp);
    setFlowSpeed('hv', val_hv);
    setFlowSpeed('wind', val_wind + val_lv_wind);
    setFlowSpeed('sol', val_sol);
    setFlowSpeed('psh', val_psh);
    setFlowSpeed('dem', val_dem);
    setFlowSpeed('exp', val_exp);
    // ------------------------------

    const timeLabels = data.history.map(h => new Date(h.time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}));
    
    if(fourDemandChartInstance) {
        fourDemandChartInstance.data.labels = timeLabels;
        fourDemandChartInstance.data.datasets[0].data = smoothData(natArr, 9);
        fourDemandChartInstance.data.datasets[1].data = smoothData(transArr, 9);
        fourDemandChartInstance.data.datasets[2].data = smoothData(netArr, 9);
        fourDemandChartInstance.data.datasets[3].data = smoothData(groArr, 9);
        fourDemandChartInstance.data.datasets[0].borderColor = activeConfig.demand.national;
        fourDemandChartInstance.data.datasets[1].borderColor = activeConfig.demand.transmission;
        fourDemandChartInstance.data.datasets[2].borderColor = activeConfig.demand.net;
        fourDemandChartInstance.data.datasets[3].borderColor = activeConfig.demand.gross;
        fourDemandChartInstance.update();
    } else {
        fourDemandChartInstance = new Chart(document.getElementById('fourDemandChart').getContext('2d'), {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: 'National Demand', data: smoothData(natArr, 9), borderColor: activeConfig.demand.national, borderWidth: 2, fill: false, pointRadius: 0, tension: 0.4 },
                    { label: 'Transmission System', data: smoothData(transArr, 9), borderColor: activeConfig.demand.transmission, borderWidth: 2, fill: false, pointRadius: 0, tension: 0.4 },
                    { label: 'Actual Net', data: smoothData(netArr, 9), borderColor: activeConfig.demand.net, borderWidth: 2, fill: false, pointRadius: 0, tension: 0.4 },
                    { label: 'Actual Gross', data: smoothData(groArr, 9), borderColor: activeConfig.demand.gross, borderWidth: 2, fill: false, pointRadius: 0, tension: 0.4 }
                ]
            },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { min: 0, grid: { color: '#3F3F46' } } } }
        });
    }

    let hexCyanRgb = hexToRgbChannels(activeConfig.theme.brand_cyan).replace(/ /g, ',');
    let hexPinkRgb = hexToRgbChannels(activeConfig.theme.octo_pink).replace(/ /g, ',');

    sparkDemand = buildSparkline(sparkDemand, 'demandSparkline', data.history.map(h => h.demand_mw), timeLabels, '#D4D4D8', 'rgba(212, 212, 216, 0.1)'); 
    sparkGen = buildSparkline(sparkGen, 'genSparkline', data.history.map(h => h.total_generation_mw), timeLabels, activeConfig.theme.brand_cyan, `rgba(${hexCyanRgb}, 0.1)`); 
    sparkFlow = buildSparkline(sparkFlow, 'flowSparkline', data.history.map(h => h.net_flow_mw), timeLabels, '#D4D4D8', 'rgba(212, 212, 216, 0.1)'); 
    sparkFreq = buildSparkline(sparkFreq, 'freqSparkline', data.history.map(h => h.grid_frequency || 50.0), timeLabels, '#D4D4D8', 'rgba(212, 212, 216, 0.1)'); 
    
    sparkPrice = buildSparkline(sparkPrice, 'priceSparkline', data.history.map(h => h.wholesale_price), timeLabels, priceColorStr, `rgba(${priceValObj.r}, ${priceValObj.g}, ${priceValObj.b}, 0.1)`);
    sparkMiPrice = buildSparkline(sparkMiPrice, 'miPriceSparkline', data.history.map(h => h.market_index_price), timeLabels, miPriceColorStr, `rgba(${miPriceValObj.r}, ${miPriceValObj.g}, ${miPriceValObj.b}, 0.1)`);
    sparkNiv = buildSparkline(sparkNiv, 'nivSparkline', data.history.map(h => h.net_imbalance_volume || 0), timeLabels, nivColor, `rgba(${nivRgb}, 0.1)`);
    
    sparkPwLoad = buildSparkline(sparkPwLoad, 'pwLoadSpark', data.history.map(h => h.pw_home_w), timeLabels, '#D4D4D8', 'rgba(212, 212, 216, 0.1)'); 
    sparkPwSolar = buildSparkline(sparkPwSolar, 'pwSolarSpark', data.history.map(h => Math.max(0, h.pw_solar_w)), timeLabels, activeConfig.fuels.solar, `rgba(${hexToRgbChannels(activeConfig.fuels.solar).replace(/ /g, ',')}, 0.1)`, 0, 5000); 
    sparkPwBatt = buildSparkline(sparkPwBatt, 'pwBattSpark', data.history.map(h => appBatteryLevel(h.pw_level)), timeLabels, '#A1A1AA', 'rgba(161, 161, 170, 0.1)', 0, 100);
    sparkPwGrid = buildSparkline(sparkPwGrid, 'pwGridSpark', data.history.map(h => h.pw_grid_w), timeLabels, activeConfig.theme.brand_cyan, `rgba(${hexCyanRgb}, 0.1)`);
    
    // Home expanded charts
    chartPwLoad = buildFullChart(chartPwLoad, 'chartPwLoad', data.history.map(h => h.pw_home_w), timeLabels, '#D4D4D8', 'rgba(212, 212, 216, 0.1)', true);
    chartPwSolar = buildFullChart(chartPwSolar, 'chartPwSolar', data.history.map(h => Math.max(0, h.pw_solar_w)), timeLabels, activeConfig.fuels.solar, `rgba(${hexToRgbChannels(activeConfig.fuels.solar).replace(/ /g, ',')}, 0.1)`, true, 0, 5000);
    chartPwBatt = buildFullChart(chartPwBatt, 'chartPwBatt', data.history.map(h => appBatteryLevel(h.pw_level)), timeLabels, '#A1A1AA', 'rgba(161, 161, 170, 0.1)', true, 0, 100);
    chartPwGrid = buildFullChart(chartPwGrid, 'chartPwGrid', data.history.map(h => h.pw_grid_w), timeLabels, activeConfig.theme.brand_cyan, `rgba(${hexCyanRgb}, 0.1)`, true);

    const cImp = activeConfig.octopus?.color_imp || activeConfig.theme.octo_pink;
    const cExp = activeConfig.octopus?.color_exp || activeConfig.theme.octo_pink;
    const cImpRgb = hexToRgbObj(cImp);
    const cExpRgb = hexToRgbObj(cExp);

    sparkOctImp = buildSparkline(sparkOctImp, 'octImpSpark', data.history.map(h => h.oct_import_pence), timeLabels, cImp, `rgba(${cImpRgb.r}, ${cImpRgb.g}, ${cImpRgb.b}, 0.1)`);
    sparkOctExp = buildSparkline(sparkOctExp, 'octExpSpark', data.history.map(h => h.oct_export_pence), timeLabels, cExp, `rgba(${cExpRgb.r}, ${cExpRgb.g}, ${cExpRgb.b}, 0.1)`);

    document.getElementById('lbl-oct-imp').style.color = cImp;
    document.getElementById('lbl-oct-exp').style.color = cExp;

    // Setup fallbacks safely just in case the config hasn't saved yet
    const fTargetCol = activeConfig.frequency?.color_target || '#30C5D5';
    const fLimitCol = activeConfig.frequency?.color_limit || '#F6643C';
    const fLow = activeConfig.frequency?.thresh_low || 49.8;
    const fHigh = activeConfig.frequency?.thresh_high || 50.2;

    if(chartFreqDetailInstance) {
        chartFreqDetailInstance.data.labels = timeLabels;
        chartFreqDetailInstance.data.datasets[0].data = data.history.map(h => h.grid_frequency || 50.0);
        chartFreqDetailInstance.data.datasets[1].data = data.history.map(() => 50.0); 
        chartFreqDetailInstance.data.datasets[2].data = data.history.map(() => fLow); 
        chartFreqDetailInstance.data.datasets[3].data = data.history.map(() => fHigh); 
        
        // Update dynamic limits for segment coloring
        chartFreqDetailInstance.data.datasets[0].segment.borderColor = ctx => {
            const val0 = ctx.p0.parsed.y;
            const val1 = ctx.p1.parsed.y;
            if (val0 >= fHigh || val1 >= fHigh || val0 <= fLow || val1 <= fLow) {
                return fLimitCol;
            }
            return '#D4D4D8';
        };
        chartFreqDetailInstance.update();
    } else {
        chartFreqDetailInstance = new Chart(document.getElementById('chartFreqDetail').getContext('2d'), {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { 
                        label: 'Grid Frequency (Hz)', 
                        data: data.history.map(h => h.grid_frequency || 50.0), 
                        borderColor: '#D4D4D8', 
                        fill: false, 
                        borderWidth: 2, 
                        pointRadius: 0, 
                        tension: 0.3,
                        segment: {
                            borderColor: ctx => {
                                const val0 = ctx.p0.parsed.y;
                                const val1 = ctx.p1.parsed.y;
                                if (val0 >= fHigh || val1 >= fHigh || val0 <= fLow || val1 <= fLow) {
                                    return fLimitCol;
                                }
                                return '#D4D4D8'; 
                            }
                        }
                    },
                    { 
                        label: 'Target (50 Hz)', 
                        data: data.history.map(() => 50.0), 
                        borderColor: fTargetCol, 
                        borderDash: [5, 5], 
                        backgroundColor: 'transparent', 
                        fill: false, 
                        borderWidth: 1.5, 
                        pointRadius: 0, 
                        tension: 0 
                    },
                    { 
                        label: 'Lower Operational Limit', 
                        data: data.history.map(() => fLow), 
                        borderColor: fLimitCol, 
                        borderDash: [3, 3], 
                        backgroundColor: 'transparent', 
                        fill: false, 
                        borderWidth: 1, 
                        pointRadius: 0, 
                        tension: 0 
                    },
                    { 
                        label: 'Upper Operational Limit', 
                        data: data.history.map(() => fHigh), 
                        borderColor: fLimitCol, 
                        borderDash: [3, 3], 
                        backgroundColor: 'transparent', 
                        fill: false, 
                        borderWidth: 1, 
                        pointRadius: 0, 
                        tension: 0 
                    }
                ]
            },
            options: { 
                responsive: true, 
                maintainAspectRatio: false, 
                interaction: { mode: 'index', intersect: false }, 
                plugins: { legend: { display: true, labels: { color: '#D4D4D8', font: { family: "'Inter', sans-serif" } } } }, 
                scales: { 
                    x: { display: true, grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 8 } }, 
                    y: { min: 49.5, max: 50.5, grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA' } } 
                } 
            }
        });
    }

    if(chartNivDetailInstance) {
        chartNivDetailInstance.data.labels = timeLabels;
        chartNivDetailInstance.data.datasets[0].data = data.history.map(h => h.net_imbalance_volume || 0);
        chartNivDetailInstance.data.datasets[0].backgroundColor = data.history.map(h => (h.net_imbalance_volume || 0) > 0 ? (activeConfig.niv?.color_short || '#F6643C') : (activeConfig.niv?.color_long || '#30C5D5'));
        
        if (isNivOverlayActive) {
            if (chartNivDetailInstance.data.datasets.length === 1) {
                chartNivDetailInstance.data.datasets.push({
                    type: 'line',
                    label: 'Balancing Price (£/MWh)',
                    data: data.history.map(h => h.wholesale_price),
                    borderColor: '#FFFFFF', 
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    yAxisID: 'y1' 
                });
            } else {
                chartNivDetailInstance.data.datasets[1].data = data.history.map(h => h.wholesale_price);
            }
            chartNivDetailInstance.options.scales.y1.display = true;
        } else {
            if (chartNivDetailInstance.data.datasets.length > 1) {
                chartNivDetailInstance.data.datasets.pop();
            }
            chartNivDetailInstance.options.scales.y1.display = false;
        }

        chartNivDetailInstance.update();
    } else {
        chartNivDetailInstance = new Chart(document.getElementById('chartNivDetail').getContext('2d'), {
            type: 'bar',
            data: {
                labels: timeLabels,
                datasets: [{ 
                    label: 'System Imbalance (MWh)', 
                    data: data.history.map(h => h.net_imbalance_volume || 0), 
                    backgroundColor: data.history.map(h => (h.net_imbalance_volume || 0) > 0 ? (activeConfig.niv?.color_short || '#F6643C') : (activeConfig.niv?.color_long || '#30C5D5')),
                    borderRadius: 2,
                    yAxisID: 'y'
                }]
            },
            options: { 
                responsive: true, 
                maintainAspectRatio: false, 
                interaction: { mode: 'index', intersect: false }, 
                plugins: { legend: { display: true, labels: { color: '#D4D4D8', font: { family: "'Inter', sans-serif" } } } }, 
                scales: { 
                    x: { display: true, grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 8 } }, 
                    y: { type: 'linear', position: 'left', grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA' } },
                    y1: { type: 'linear', position: 'right', display: false, grid: { drawOnChartArea: false }, ticks: { color: '#FFFFFF', callback: function(value) { return '£' + value; } } }
                } 
            }
        });
    }

    if(chartPriceDetailInstance) {
        chartPriceDetailInstance.data.labels = timeLabels;
        chartPriceDetailInstance.data.datasets[0].data = data.history.map(h => h.wholesale_price);
        chartPriceDetailInstance.data.datasets[1].data = data.history.map(h => h.market_index_price);
        chartPriceDetailInstance.data.datasets[0].borderColor = priceColorStr;
        chartPriceDetailInstance.data.datasets[0].backgroundColor = `rgba(${priceValObj.r}, ${priceValObj.g}, ${priceValObj.b}, 0.2)`;
        chartPriceDetailInstance.data.datasets[1].borderColor = miPriceColorStr;
        chartPriceDetailInstance.update();
    } else {
        chartPriceDetailInstance = new Chart(document.getElementById('chartPriceDetail').getContext('2d'), {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: 'Balancing System Price', data: data.history.map(h => h.wholesale_price), borderColor: priceColorStr, backgroundColor: `rgba(${priceValObj.r}, ${priceValObj.g}, ${priceValObj.b}, 0.2)`, fill: true, borderWidth: 2, pointRadius: 0, tension: 0.3 },
                    { label: 'MIDP (EPEX SPOT)', data: data.history.map(h => h.market_index_price), borderColor: miPriceColorStr, borderDash: [4, 4], backgroundColor: 'transparent', fill: false, borderWidth: 2, pointRadius: 0, tension: 0.3 }
                ]
            },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: true, labels: { color: '#D4D4D8', font: { family: "'Inter', sans-serif" } } } }, scales: { x: { display: true, grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 8 } }, y: { grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA' } } } }
        });
    }

    if(chartOctoDetailInstance) {
        chartOctoDetailInstance.data.labels = timeLabels;
        chartOctoDetailInstance.data.datasets[0].data = data.history.map(h => h.oct_import_pence);
        chartOctoDetailInstance.data.datasets[1].data = data.history.map(h => h.oct_export_pence);
        chartOctoDetailInstance.data.datasets[0].borderColor = cImp;
        chartOctoDetailInstance.data.datasets[0].backgroundColor = `rgba(${cImpRgb.r}, ${cImpRgb.g}, ${cImpRgb.b}, 0.2)`;
        chartOctoDetailInstance.data.datasets[1].borderColor = cExp;
        chartOctoDetailInstance.update();
    } else {
        chartOctoDetailInstance = new Chart(document.getElementById('chartOctoDetail').getContext('2d'), {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [
                    { label: 'Import Rate (p/kWh)', data: data.history.map(h => h.oct_import_pence), borderColor: cImp, backgroundColor: `rgba(${cImpRgb.r}, ${cImpRgb.g}, ${cImpRgb.b}, 0.2)`, fill: true, borderWidth: 2, pointRadius: 0, tension: 0.3 },
                    { label: 'Export Rate (p/kWh)', data: data.history.map(h => h.oct_export_pence), borderColor: cExp, borderDash: [5, 5], backgroundColor: 'transparent', fill: false, borderWidth: 2, pointRadius: 0, tension: 0.3 }
                ]
            },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: true, labels: { color: '#D4D4D8', font: { family: "'Inter', sans-serif" } } } }, scales: { x: { display: true, grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 8 } }, y: { grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA' } } } }
        });
    }

    let bridgedIntensity = [];
    let lastValidCarbon = rawIntensity.find(v => v > 0) || 0;
    for (let i = 0; i < rawIntensity.length; i++) {
        if (rawIntensity[i] === 0 || rawIntensity[i] === null) { bridgedIntensity.push(lastValidCarbon); } 
        else { bridgedIntensity.push(rawIntensity[i]); lastValidCarbon = rawIntensity[i]; }
    }
    
 // ... preceding code for bridgedIntensity and smoothedIntensity ...
    const smoothedIntensity = smoothData(bridgedIntensity, 10);
    sparkCarbon = buildSparkline(sparkCarbon, 'carbonSparkline', smoothedIntensity, timeLabels, ragColor, ragBg);
    
    const carbCtx = document.getElementById('carbonHistoryChart').getContext('2d');
    let carbGrad = carbCtx.createLinearGradient(0, 0, 0, 400); 
    carbGrad.addColorStop(0, activeConfig.carbon.high); 
    carbGrad.addColorStop(0.5, activeConfig.carbon.med); 
    carbGrad.addColorStop(1, activeConfig.carbon.low);
    
    let highRgb = hexToRgbChannels(activeConfig.carbon.high).replace(/ /g, ','); 
    let medRgb = hexToRgbChannels(activeConfig.carbon.med).replace(/ /g, ','); 
    let lowRgb = hexToRgbChannels(activeConfig.carbon.low).replace(/ /g, ',');
    
    let carbBgChart = carbCtx.createLinearGradient(0, 0, 0, 400); 
    carbBgChart.addColorStop(0, `rgba(${highRgb}, 0.2)`); 
    carbBgChart.addColorStop(0.5, `rgba(${medRgb}, 0.2)`); 
    carbBgChart.addColorStop(1, `rgba(${lowRgb}, 0.2)`);
    
    // Calculate the dynamic max for the Y-axis
    const currentMaxCarbon = Math.max(...smoothedIntensity);
    const chartMax = currentMaxCarbon > 250 ? 500 : 250; 

    if(carbonChartInstance) { 
        carbonChartInstance.data.datasets[0].data = smoothedIntensity; 
        carbonChartInstance.data.datasets[0].borderColor = carbGrad; 
        carbonChartInstance.data.datasets[0].backgroundColor = carbBgChart; 
        carbonChartInstance.options.scales.y.max = chartMax; // Updates the existing chart max
        carbonChartInstance.update(); 
    } else { 
        carbonChartInstance = new Chart(carbCtx, { 
            type: 'line', 
            data: { 
                labels: timeLabels, 
                datasets: [{ 
                    label: 'Intensity', 
                    data: smoothedIntensity, 
                    borderColor: carbGrad, 
                    backgroundColor: carbBgChart, 
                    fill: true, 
                    borderWidth: 2, 
                    pointRadius: 0, 
                    tension: 0.4 
                }] 
            }, 
            options: { 
                responsive: true, 
                maintainAspectRatio: false, 
                plugins: { legend: { display: false } }, 
                scales: { 
                    x: { grid: { display: false } }, 
                    y: { min: 0, max: chartMax, grid: { color: '#3F3F46' } } // Sets initial max
                } 
            } 
        }); 
    }
}

document.addEventListener('DOMContentLoaded', () => { updateDashboard(); setInterval(updateDashboard, 120000); });
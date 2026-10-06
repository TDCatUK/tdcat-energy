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
    "Other": "Generation Elexon doesn't put under a main fuel type, such as energy-from-waste and some smaller plants. Coal and oil are added here too; GB's last coal power station closed in September 2024.",
    "Grid Batteries": "An unofficial estimate. Every 5 minutes this adds up the current level of each battery unit in the Balancing Mechanism: its own Physical Notification, or the latest NESO instruction (Bid-Offer Acceptance) where there is one. Batteries outside the Balancing Mechanism aren't included, and these are planned rather than metered levels, so treat it as an indication. Above zero = discharging into the grid, below zero = charging. See the About page for details.",
    "Batteries (est.)": "Unofficial estimate of grid-scale batteries discharging into the grid right now (charging is demand, so it isn't shown here). Every 5 minutes this adds up the current level of each battery unit in the Balancing Mechanism: its own Physical Notification, or the latest NESO instruction (Bid-Offer Acceptance) where there is one. Batteries outside the Balancing Mechanism aren't included, and these are planned rather than metered levels, so treat it as an indication. Above zero = discharging into the grid, below zero = charging. See the About page for details."
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

const sortOrder = ["Wind", "LV Wind", "Solar", "Hydro", "Biomass", "Nuclear", "Imports", "Other", "OCG", "CCGT", "Pumped Storage", "Batteries (est.)"];

let genChartInstance, flowChartInstance, historyChartInstance, carbonChartInstance, fuelDetailChartInstance, fourDemandChartInstance;
let sparkDemand, sparkGen, sparkFlow, sparkFreq, sparkPrice, sparkMiPrice, sparkNiv, sparkCarbon, sparkPwLoad, sparkPwSolar, sparkPwBatt, sparkPwGrid, sparkOctImp, sparkOctExp;
let chartPwLoad, chartPwSolar, chartPwBatt, chartPwGrid, chartPriceDetailInstance, chartOctoDetailInstance;
let chartFreqDetailInstance, chartNivDetailInstance, chartBatteryInstance;
let sparkGasLinepack, sparkGasSupply, sparkGasDemand, chartGasSupply, chartGasDemand, chartGasHistory;
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
    if(!el.classList.contains('hidden')) {
        if (chartFreqDetailInstance) chartFreqDetailInstance.resize();
        loadFrequency();
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
        root.style.setProperty('--color-batt', config.fuels.battery || '#A78BFA');
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
            applyIcon('icon-batt', config.flow.icons.batt || 'fa-solid fa-battery-half');
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
        if (currentSelectedFuel === 'battery') return (h.bess_discharge_mw || 0) / 1000;  // unofficial estimate, discharging only
        const f = h.mix.find(x => x.fuel === currentSelectedFuel);
        return f ? f.mw / 1000 : 0;
    });
    const dataArray = smoothData(rawData, 9);
    
    const colorStr = activeConfig.fuels[currentSelectedFuel];
    let rgb = hexToRgbChannels(colorStr).replace(/ /g, ',');
    const bgStr = `rgba(${rgb}, 0.2)`;

    fuelDetailChartInstance = buildFullChart(fuelDetailChartInstance, 'fuelDetailChart', dataArray, timeLabels, colorStr, bgStr, true);
}

// Whether the 24-hour mix includes the unofficial battery estimate (on by default, remembered per browser)
let showBatteryInMix = true;
try { showBatteryInMix = localStorage.getItem('showBatteryInMix') !== 'false'; } catch (e) {}

function setBatteryInMix(on) {
    showBatteryInMix = on;
    try { localStorage.setItem('showBatteryInMix', on); } catch (e) {}
    if (currentGridData && activeConfig) renderDashboardData(currentGridData);
}

function styleBatteryPills() {
    const active = "px-4 py-1 rounded-full bg-ui-grey text-white font-semibold shadow-sm transition-all";
    const idle = "px-4 py-1 rounded-full text-ui-light hover:text-white transition-all";
    document.querySelectorAll('.batt-pill-on').forEach(b => b.className = 'batt-pill-on ' + (showBatteryInMix ? active : idle));
    document.querySelectorAll('.batt-pill-off').forEach(b => b.className = 'batt-pill-off ' + (showBatteryInMix ? idle : active));
}

function renderHistoryChart() {
    if(!cachedHistoryData.length || !activeConfig) return;
    styleBatteryPills();
    const timeLabels = cachedHistoryData.map(h => new Date(h.time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}));
    const apiFuels = ["nuclear", "ccgt", "ocg", "other", "imports", "biomass", "pumped_storage", ...(showBatteryInMix ? ["battery"] : []), "hydro", "solar", "lv_wind", "wind"];
    const historyColours = { "wind": activeConfig.fuels.wind, "lv_wind": activeConfig.fuels.lv_wind || '#5FB035', "solar": activeConfig.fuels.solar, "hydro": activeConfig.fuels.hydro, "pumped_storage": activeConfig.fuels.pumped_storage, "biomass": activeConfig.fuels.biomass, "nuclear": activeConfig.fuels.nuclear, "imports": activeConfig.fuels.imports, "other": activeConfig.fuels.other, "ocg": activeConfig.fuels.ocg, "ccgt": activeConfig.fuels.ccgt };
    
    historyColours.battery = activeConfig.fuels.battery || '#A78BFA';

    // MW per fuel for each row. % is worked out here so it stays correct with the battery estimate on or off.
    const rowsMw = cachedHistoryData.map(h => {
        const mw = {};
        h.mix.forEach(m => mw[m.fuel] = m.mw);
        if (showBatteryInMix) mw.battery = h.bess_discharge_mw || 0;
        return mw;
    });
    const rowTotals = rowsMw.map(mw => Object.values(mw).reduce((a, b) => a + b, 0));

    let datasets = apiFuels.map(fuel => ({
        type: 'line', label: fuel === 'battery' ? 'BATTERIES (EST.)' : fuel.toUpperCase(),
        data: smoothData(rowsMw.map((mw, i) => historyMode === 'GW' ? (mw[fuel] || 0) / 1000 : (rowTotals[i] ? (mw[fuel] || 0) / rowTotals[i] * 100 : 0)), 9), 
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

// ---------- When Demand Shifts & the duck curve (NESO half-hourly data, fetched at most hourly) ----------

// Labelled vertical dashed lines: options.plugins.verticalMarkers = { lines: [{ index, label, colour }] }
const verticalMarkersPlugin = {
    id: 'verticalMarkers',
    afterDatasetsDraw(chart, args, opts) {
        if (!opts || !opts.lines) return;
        const { ctx, chartArea, scales } = chart;
        ctx.save();
        opts.lines.forEach((m, n) => {
            if (m.index == null || m.index < 0) return;
            const px = scales.x.getPixelForValue(m.index);
            ctx.strokeStyle = m.colour || '#A1A1AA'; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
            ctx.beginPath(); ctx.moveTo(px, chartArea.top); ctx.lineTo(px, chartArea.bottom); ctx.stroke();
            if (m.label) {
                const right = px > (chartArea.left + chartArea.right) / 2;
                ctx.setLineDash([]); ctx.fillStyle = m.colour || '#A1A1AA'; ctx.font = "600 10px 'Inter', sans-serif";
                ctx.textAlign = right ? 'right' : 'left';
                ctx.fillText(m.label, px + (right ? -4 : 4), chartArea.top + 10 + n * 12);
            }
        });
        ctx.restore();
    }
};
Chart.register(verticalMarkersPlugin);

let demandRecentRows = null, demandRecentFetchedAt = 0, duckMonthLoaded = null, duckChart;
const momentCharts = {};

const minutesOf = text => { const [h, m] = String(text || '00:00').split(':').map(Number); return h * 60 + (m || 0); };
const hhmm = mins => `${String(Math.floor(mins / 60) % 24).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`;
const dayBefore = day => { const d = new Date(day + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() - 1); return d.toISOString().slice(0, 10); };
const signedGw = v => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)} GW`;
const setNote = (id, text) => { const el = document.getElementById(id); if (el) el.innerText = text; };

function renderDemandPatterns() {
    if (!document.getElementById('demand-moments')) return;  // page from before these charts existed
    if (demandRecentRows && Date.now() - demandRecentFetchedAt < 3600 * 1000) return;  // drawn already; the data changes daily
    fetch('/api/demand/recent').then(r => r.ok ? r.json() : null).then(d => {
        if (d && d.rows && d.rows.length) { demandRecentRows = d.rows; demandRecentFetchedAt = Date.now(); drawMoments(); }
        // Redraw the duck curve too: its last-30-days line and the solar records change daily
        loadDuckCurve(duckMonthLoaded === null ? new Date().getMonth() + 1 : duckMonthLoaded);
    }).catch(() => {});
}

// Half-hourly demand (GW) in a time window, which may run past midnight, for each of the last 30 complete days
function demandWindow(startMin, endMin) {
    if (startMin < 0) { startMin += 1440; endMin += 1440; }
    const slots = [];
    for (let m = startMin; m <= endMin; m += 30) slots.push(m);
    const days = {};
    demandRecentRows.forEach(r => {
        let m = minutesOf(r.t.slice(11, 16)), day = r.t.slice(0, 10);
        if (endMin >= 1440 && m < startMin) { m += 1440; day = dayBefore(day); }
        const i = slots.indexOf(m);
        if (i < 0) return;
        const d = days[day] = days[day] || { nd: new Array(slots.length).fill(null), solar: new Array(slots.length).fill(null) };
        d.nd[i] = r.nd / 1000;
        d.solar[i] = r.solar / 1000;
    });
    const keys = Object.keys(days).sort().filter(k => days[k].nd.every(v => v != null)).slice(-30);
    const mean = series => slots.map((_, i) => keys.reduce((a, k) => a + days[k][series][i], 0) / (keys.length || 1));
    return { slots, labels: slots.map(hhmm), keys, days, avg: mean('nd'), avgSolar: mean('solar') };
}

// Faint line per day, bold average, dashed latest day, marker lines, and bars of the half-hour-to-half-hour change
function drawMoment(name, w, colour, markers, extra = []) {
    const latest = w.keys[w.keys.length - 1];
    const latestLabel = new Date(latest + 'T12:00:00Z').toLocaleDateString([], { day: 'numeric', month: 'short' });
    const datasets = [
        ...w.keys.map(k => ({ label: '', data: w.days[k].nd, borderColor: 'rgba(161, 161, 170, 0.18)', borderWidth: 1, pointRadius: 0, tension: 0 })),
        ...extra,
        { label: '30-day average', data: w.avg, borderColor: colour, borderWidth: 3, pointRadius: 0, tension: 0 },
        { label: `Latest (${latestLabel})`, data: w.days[latest].nd, borderColor: '#FFFFFF', borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0, tension: 0 }
    ];
    const id = 'chartMoment' + name;
    if (momentCharts[id]) momentCharts[id].destroy();
    momentCharts[id] = new Chart(document.getElementById(id).getContext('2d'), {
        type: 'line',
        data: { labels: w.labels, datasets },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: false }, verticalMarkers: { lines: markers },
                tooltip: { filter: item => item.dataset.label !== '', callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw.toFixed(2)} GW` } } },
            scales: { x: { grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 5, maxRotation: 0 } },
                      y: { grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA', callback: v => v + ' GW' } } }
        }
    });

    // Bar i is the step from half-hour i-1 to half-hour i, so the bar at a marker is the step across that time
    const change = w.avg.map((v, i) => i ? v - w.avg[i - 1] : null);
    const marked = markers.map(m => m.index);
    const cid = id + 'Change';
    if (momentCharts[cid]) momentCharts[cid].destroy();
    momentCharts[cid] = new Chart(document.getElementById(cid).getContext('2d'), {
        type: 'bar',
        data: { labels: w.labels, datasets: [{ label: 'Change', data: change, borderRadius: 2,
            backgroundColor: change.map((v, i) => marked.includes(i) ? colour : 'rgba(161, 161, 170, 0.45)') }] },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { display: false }, tooltip: { callbacks: {
                title: items => `${w.labels[items[0].dataIndex - 1]} → ${w.labels[items[0].dataIndex]}`,
                label: ctx => `Average change: ${signedGw(ctx.raw)}` } } },
            scales: { x: { display: false }, y: { grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA', maxTicksLimit: 3, callback: v => (v > 0 ? '+' : '') + v.toFixed(1) } } }
        }
    });
    return change;
}

function stepNote(change, i, time) {
    if (i < 2) return '';
    const after = change[i + 1] != null ? `, the one after ${signedGw(change[i + 1])}` : '';
    return `Across ${time}, average demand steps ${signedGw(change[i])}. The half-hour before moved ${signedGw(change[i - 1])}${after}.`;
}

function drawMoments() {
    const times = activeConfig.patterns || {};
    const offEnd = minutesOf(times.offpeak_end || '05:30'), offStart = minutesOf(times.offpeak_start || '23:30');
    const cyan = activeConfig.theme.brand_cyan, orange = activeConfig.theme.brand_orange, purple = activeConfig.fuels.battery || '#A78BFA';

    // Morning: two hours either side of the end of off-peak
    const morning = demandWindow(offEnd - 120, offEnd + 120);
    if (!morning.keys.length) { setNote('moment-morning-note', 'Not enough data yet.'); return; }
    const iEnd = morning.slots.indexOf(offEnd < 120 ? offEnd + 1440 : offEnd);
    setNote('moment-morning-note', stepNote(drawMoment('Morning', morning, cyan, [{ index: iEnd, label: `Off-peak ends ${hhmm(offEnd)}`, colour: cyan }]), iEnd, hhmm(offEnd)));

    // Evening: 15:00 to 21:00, with rooftop solar added back so the gap shows how much of the climb is the sun setting
    const evening = demandWindow(15 * 60, 21 * 60);
    const solarPeak = {};
    demandRecentRows.forEach(r => { const d = r.t.slice(0, 10); solarPeak[d] = Math.max(solarPeak[d] || 0, r.solar / 1000); });
    const fades = evening.keys.map(k => evening.days[k].solar.findIndex(v => v < 0.1 * (solarPeak[k] || 0))).filter(i => i >= 0);
    const iFade = fades.length ? Math.round(fades.reduce((a, b) => a + b, 0) / fades.length) : -1;
    const iPeak = evening.avg.indexOf(Math.max(...evening.avg));
    const withSolar = { label: 'Average incl. rooftop solar', data: evening.avg.map((v, i) => v + evening.avgSolar[i]), borderColor: activeConfig.fuels.solar, borderDash: [2, 3], borderWidth: 1.5, pointRadius: 0, tension: 0 };
    drawMoment('Evening', evening, orange, [
        { index: iFade, label: iFade >= 0 ? `Solar fades ~${evening.labels[iFade]}` : '', colour: activeConfig.fuels.solar },
        { index: iPeak, label: `Peak ${evening.labels[iPeak]}`, colour: orange }
    ], [withSolar]);
    setNote('moment-evening-note', `From 15:00 the grid's demand climbs ${(evening.avg[iPeak] - evening.avg[0]).toFixed(2)} GW to its ${evening.labels[iPeak]} peak.` +
        (iFade >= 0 ? ` Rooftop solar has faded by about ${evening.labels[iFade]}; the dotted line adds it back, so the gap is the part of the climb caused by the sun going down.` : ''));

    // Night: two hours either side of the start of off-peak (this window runs past midnight)
    const night = demandWindow(offStart - 120, offStart + 120);
    const iStart = night.slots.indexOf(offStart < 120 ? offStart + 1440 : offStart);
    setNote('moment-night-note', stepNote(drawMoment('Night', night, purple, [{ index: iStart, label: `Off-peak starts ${hhmm(offStart)}`, colour: purple }]), iStart, hhmm(offStart)));

    const last = morning.keys[morning.keys.length - 1];
    setNote('moments-asof', `Source: NESO national demand, ${morning.keys.length} days to ${new Date(last + 'T12:00:00Z').toLocaleDateString([], { day: 'numeric', month: 'short' })}`);
}

function loadDuckCurve(month) {
    const select = document.getElementById('duck-month');
    if (!select) return;
    if (!select.options.length) {
        for (let m = 1; m <= 12; m++) select.add(new Option(new Date(Date.UTC(2024, m - 1, 1)).toLocaleDateString([], { month: 'long', timeZone: 'UTC' }), m));
    }
    select.value = month;
    duckMonthLoaded = month;
    fetch(`/api/demand/duck?month=${month}`).then(r => r.ok ? r.json() : null).then(d => { if (d) drawDuck(d); }).catch(() => {});
}

function drawDuck(d) {
    const labels = Array.from({ length: 48 }, (_, i) => hhmm(i * 30));
    const monthName = new Date(Date.UTC(2024, d.month - 1, 1)).toLocaleDateString([], { month: 'long', timeZone: 'UTC' });
    const all = Object.keys(d.years).filter(y => d.years[y].days >= 15).sort();
    if (!all.length) return;
    // Every fifth year from the first, plus the latest two, keeps the chart readable
    const shown = all.filter((y, i) => (+y - +all[0]) % 5 === 0 || i >= all.length - 2);
    const latest = shown[shown.length - 1];
    const gw = arr => arr.map(v => v == null ? null : v / 1000);
    const datasets = shown.map((y, i) => ({
        label: y, data: gw(d.years[y].nd), pointRadius: 0, tension: 0.2,
        borderColor: y === latest ? activeConfig.theme.brand_orange : (i === shown.length - 2 ? activeConfig.theme.brand_cyan : `rgba(161, 161, 170, ${(0.3 + 0.5 * i / shown.length).toFixed(2)})`),
        borderWidth: y === latest ? 3 : 1.5
    }));
    datasets.push({ label: `${latest} + rooftop solar`, data: d.years[latest].nd.map((v, i) => (v + d.years[latest].solar[i]) / 1000),
        borderColor: activeConfig.fuels.solar, borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0, tension: 0.2 });
    // The last 30 days, when looking at the current month
    if (demandRecentRows && d.month === new Date().getMonth() + 1) {
        const sums = new Array(48).fill(0), counts = new Array(48).fill(0);
        const since = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
        demandRecentRows.filter(r => r.t.slice(0, 10) >= since).forEach(r => { const i = minutesOf(r.t.slice(11, 16)) / 30; sums[i] += r.nd / 1000; counts[i]++; });
        datasets.push({ label: 'Last 30 days', data: sums.map((s, i) => counts[i] ? s / counts[i] : null), borderColor: '#FFFFFF', borderDash: [2, 3], borderWidth: 2, pointRadius: 0, tension: 0.2 });
    }
    if (duckChart) duckChart.destroy();
    duckChart = new Chart(document.getElementById('chartDuck').getContext('2d'), {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: true, labels: { color: '#D4D4D8', font: { family: "'Inter', sans-serif" } } },
                tooltip: { callbacks: { label: ctx => ctx.raw == null ? null : `${ctx.dataset.label}: ${ctx.raw.toFixed(1)} GW` } } },
            scales: { x: { grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 12, maxRotation: 0 } },
                      y: { grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA', callback: v => v + ' GW' } } }
        }
    });

    // Facts: the record solar share, when solar first beat the grid's demand, and how the midday dip has deepened
    const records = d.records.filter(r => r.solar_share_pct != null);
    const best = records.reduce((a, r) => (!a || r.solar_share_pct > a.solar_share_pct) ? r : a, null);
    if (best) {
        const when = new Date(best.share_date + 'T12:00:00Z').toLocaleDateString([], { day: 'numeric', month: 'long', year: 'numeric' });
        // Flag a record set in the last two weeks
        const isNew = Date.now() - new Date(best.share_date + 'T12:00:00Z').getTime() < 14 * 86400000;
        document.getElementById('duck-fact-share').innerHTML =
            (isNew ? `<span class="inline-block text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 rounded mr-1 text-ui-darkest" style="background: ${activeConfig.theme.brand_orange};">New record</span>` : '') +
            `${best.solar_share_pct.toFixed(0)}% of GB electricity use came from rooftop solar at ${hhmm((best.share_period - 1) * 30)} on ${when}: ${(best.share_solar / 1000).toFixed(1)} GW of solar while the grid supplied ${(best.share_nd / 1000).toFixed(1)} GW.`;
    }
    const over = records.filter(r => r.halfhours_solar_over_nd > 0);
    setNote('duck-fact-over', over.length
        ? `Rooftop solar produced more than the grid itself was supplying in ${over.map(r => `${r.halfhours_solar_over_nd} half-hours in ${r.year}`).join(', ')}. It had never happened before ${over[0].year}.`
        : `Not yet. Rooftop solar has never produced more than the grid itself was supplying.`);
    const first = shown[0], ratio = y => (d.years[y].nd[26] / d.years[y].nd[2] - 1) * 100;
    const describe = p => `${Math.abs(p).toFixed(0)}% ${p >= 0 ? 'above' : 'below'}`;
    setNote('duck-fact-belly', `In ${monthName} ${first}, grid demand at 13:00 was ${describe(ratio(first))} demand at 01:00. In ${monthName} ${latest} it was ${describe(ratio(latest))}.`);
}

// === Grid frequency at full resolution (every 15-second reading) ===
let freqHours = 1, chartFreqFull;
const PILL_ACTIVE = "px-4 py-1 rounded-full bg-ui-grey text-white font-semibold shadow-sm transition-all";
const PILL_IDLE = "px-4 py-1 rounded-full text-ui-light hover:text-white transition-all";
const clockTime = (t, seconds = false) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) });
const durationText = secs => secs < 60 ? `${secs}s`
    : secs < 3600 ? `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, '0')}s`
    : `${Math.floor(secs / 3600)}h ${String(Math.floor(secs % 3600 / 60)).padStart(2, '0')}m`;

function setFreqRange(hours) {
    freqHours = hours;
    document.querySelectorAll('#freq-range-pills button').forEach(b => b.className = +b.dataset.hours === hours ? PILL_ACTIVE : PILL_IDLE);
    loadFrequency();
}

// Today's low, high and time outside the limits on the card and panel; the chart only while the panel is open
function loadFrequency() {
    const panel = document.getElementById('freq-expanded-chart');
    const open = panel && !panel.classList.contains('hidden') && document.getElementById('chartFreqFull');
    fetch(`/api/frequency?hours=${open ? freqHours : 0.25}`).then(r => r.ok ? r.json() : null).then(d => {
        if (!d || !d.today) return;
        const t = d.today, limitCol = activeConfig.frequency?.color_limit || '#F6643C';
        const outside = v => v < d.low || v > d.high;
        setNote('freq-today', `Today ${t.min.toFixed(2)}–${t.max.toFixed(2)} Hz`);
        setNote('freq-stat-min', `${t.min.toFixed(3)} Hz`);
        setNote('freq-stat-min-t', `at ${clockTime(t.min_t, true)}`);
        setNote('freq-stat-max', `${t.max.toFixed(3)} Hz`);
        setNote('freq-stat-max-t', `at ${clockTime(t.max_t, true)}`);
        setNote('freq-stat-outside-label', `Outside ${d.low}–${d.high} Hz today`);
        setNote('freq-stat-outside', t.outside_secs ? durationText(t.outside_secs) : 'None');
        setNote('freq-stat-outside-pct', `${t.outside_pct.toFixed(1)}% of the day so far` +
            (t.outside_statutory_secs ? `, ${durationText(t.outside_statutory_secs)} outside the legal limits` : ''));
        setNote('freq-stat-count', t.readings.toLocaleString());
        [['freq-stat-min', t.min], ['freq-stat-max', t.max]].forEach(([id, v]) => { const el = document.getElementById(id); if (el) el.style.color = outside(v) ? limitCol : ''; });
        const outEl = document.getElementById('freq-stat-outside');
        if (outEl) outEl.style.color = t.outside_secs ? limitCol : '';
        if (open) drawFrequency(d);
    }).catch(() => {});
}

function drawFrequency(d) {
    if (!d.readings.length) return;
    const limitCol = activeConfig.frequency?.color_limit || '#F6643C', targetCol = activeConfig.frequency?.color_target || '#30C5D5';
    const points = d.readings.map(([t, hz]) => ({ x: t * 1000, y: hz }));
    const span = [points[0].x, points[points.length - 1].x];
    const flat = y => [{ x: span[0], y }, { x: span[1], y }];
    const outside = v => v < d.low || v > d.high;
    const values = d.readings.map(r => r[1]);
    // Always show the operational limits, and round the axis to 0.05 Hz
    const lo = Math.floor((Math.min(d.low, ...values) - 0.01) * 20) / 20, hi = Math.ceil((Math.max(d.high, ...values) + 0.01) * 20) / 20;
    const datasets = [
        { label: 'Frequency', data: points, borderColor: '#D4D4D8', borderWidth: 1.5, pointRadius: 0, tension: 0,
          segment: { borderColor: ctx => outside(ctx.p0.parsed.y) || outside(ctx.p1.parsed.y) ? limitCol : '#D4D4D8' } },
        { label: '50 Hz target', data: flat(50), borderColor: targetCol, borderDash: [5, 5], borderWidth: 1.5, pointRadius: 0 },
        { label: `Operational limits (${d.low}–${d.high} Hz)`, data: flat(d.low), borderColor: limitCol, borderDash: [3, 3], borderWidth: 1, pointRadius: 0 },
        { label: '', data: flat(d.high), borderColor: limitCol, borderDash: [3, 3], borderWidth: 1, pointRadius: 0 }
    ];
    if (chartFreqFull) chartFreqFull.destroy();
    chartFreqFull = new Chart(document.getElementById('chartFreqFull').getContext('2d'), {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false, parsing: false, normalized: true,
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            plugins: {
                legend: { display: true, labels: { color: '#D4D4D8', filter: item => item.text !== '' } },
                decimation: { enabled: true, algorithm: 'min-max' },
                tooltip: { filter: item => item.datasetIndex === 0, callbacks: {
                    title: items => clockTime(items[0].parsed.x / 1000, true),
                    label: ctx => `${ctx.parsed.y.toFixed(3)} Hz` } }
            },
            scales: {
                x: { type: 'linear', min: span[0], max: span[1], grid: { display: false },
                     // Ticks on round local times: every 10 minutes, hour or 3 hours depending on the range
                     afterBuildTicks: axis => {
                         const step = (span[1] - span[0] <= 3600e3 ? 10 : span[1] - span[0] <= 6 * 3600e3 ? 60 : 180) * 60e3;
                         const offset = new Date(span[1]).getTimezoneOffset() * 60e3;
                         const ticks = [];
                         for (let t = Math.ceil((axis.min - offset) / step) * step + offset; t <= axis.max; t += step) ticks.push({ value: t });
                         axis.ticks = ticks;
                     },
                     ticks: { color: '#A1A1AA', maxRotation: 0, callback: v => clockTime(v / 1000) } },
                y: { min: lo, max: hi, grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA', callback: v => v.toFixed(2) } }
            }
        }
    });
}

// === Upcoming Agile prices and the carbon forecast ===
let agileChart, agileFetchedAt = 0;

// Shaded x-ranges behind the data: options.plugins.shadedBands = { bands: [{ from, to, colour, label }] } (category indices)
const shadedBandsPlugin = {
    id: 'shadedBands',
    beforeDatasetsDraw(chart, args, opts) {
        if (!opts || !opts.bands) return;
        const { ctx, chartArea, scales } = chart;
        const step = scales.x.getPixelForValue(1) - scales.x.getPixelForValue(0);
        ctx.save();
        opts.bands.forEach(b => {
            if (b.from == null) return;
            const left = scales.x.getPixelForValue(b.from) - step / 2, right = scales.x.getPixelForValue(b.to) + step / 2;
            ctx.globalAlpha = 0.15; ctx.fillStyle = b.colour;
            ctx.fillRect(left, chartArea.top, right - left, chartArea.bottom - chartArea.top);
            if (b.label) {
                const flip = left > (chartArea.left + chartArea.right) / 2;
                ctx.globalAlpha = 1; ctx.font = "600 10px 'Inter', sans-serif"; ctx.textAlign = flip ? 'right' : 'left';
                ctx.fillText(b.label, flip ? right - 4 : left + 4, chartArea.top + 10);
            }
        });
        ctx.restore();
    }
};
Chart.register(shadedBandsPlugin);

// The run of `size` consecutive slots with the lowest (or highest) average, ignoring runs with gaps
function bestWindow(values, size, highest = false) {
    let best = null;
    for (let i = 0; i + size <= values.length; i++) {
        const run = values.slice(i, i + size);
        if (run.some(v => v == null)) continue;
        const avg = run.reduce((a, b) => a + b, 0) / size;
        if (!best || (highest ? avg > best.avg : avg < best.avg)) best = { start: i, end: i + size - 1, avg };
    }
    return best;
}

const slotTime = t => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const slotDay = t => {
    const d = new Date(t), now = new Date();
    const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
    return days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : d.toLocaleDateString([], { weekday: 'long' });
};

function loadAgileForecast() {
    if (!document.getElementById('chartAgile')) return;  // page from before this section existed
    if (agileChart && Date.now() - agileFetchedAt < 600e3) return;  // prices and forecasts change half-hourly
    fetch('/api/forecast').then(r => r.ok ? r.json() : null).then(d => {
        if (d && (d.agile.length || d.carbon.length)) { agileFetchedAt = Date.now(); drawAgileForecast(d); }
    }).catch(() => {});
}

function drawAgileForecast(d) {
    // One slot per half-hour from now to the end of the carbon forecast (48 h) or the published prices, if later
    const start = Date.parse(d.from), imp = {}, exp = {}, carbon = {}, band = {};
    d.agile.forEach(r => { imp[Date.parse(r.t)] = r.import; exp[Date.parse(r.t)] = r.export; });
    d.carbon.forEach(r => { carbon[Date.parse(r.t)] = r.forecast; band[Date.parse(r.t)] = r.index; });
    const last = Math.max(start, ...Object.keys(imp).map(Number), ...Object.keys(carbon).map(Number));
    const times = [];
    for (let t = start; t <= last; t += 1800e3) times.push(t);
    const importP = times.map(t => imp[t] ?? null), exportP = times.map(t => exp[t] ?? null), carbonG = times.map(t => carbon[t] ?? null);

    const cheap = bestWindow(importP, 6), peak = bestWindow(importP, 6, true), greenest = bestWindow(carbonG, 6);
    const pick = (values, better) => values.reduce((a, v, i) => v != null && (a < 0 || better(v, values[a])) ? i : a, -1);
    const iCheapest = pick(importP, (a, b) => a < b), iBestExport = pick(exportP, (a, b) => a > b);
    const span = w => `${slotTime(times[w.start])}–${slotTime(times[w.end] + 1800e3)}`;

    setNote('agile-cheap3', cheap ? span(cheap) : '---');
    setNote('agile-cheap3-note', cheap ? `${slotDay(times[cheap.start])}, averaging ${cheap.avg.toFixed(1)}p/kWh` : '');
    setNote('agile-cheap1', iCheapest >= 0 ? `${importP[iCheapest].toFixed(1)}p` : '---');
    setNote('agile-cheap1-note', iCheapest >= 0 ? `${slotDay(times[iCheapest])} at ${slotTime(times[iCheapest])}` + (importP[iCheapest] < 0 ? `: you're paid to use power` : '') : '');
    setNote('agile-green3', greenest ? span(greenest) : '---');
    setNote('agile-green3-note', greenest ? `${slotDay(times[greenest.start])}, averaging ${Math.round(greenest.avg)} gCO₂/kWh` : '');
    setNote('agile-peak3', peak ? span(peak) : '---');
    setNote('agile-peak3-note', peak ? `${slotDay(times[peak.start])}, averaging ${peak.avg.toFixed(1)}p/kWh` +
        (iBestExport >= 0 ? `. Export peaks at ${exportP[iBestExport].toFixed(1)}p (${slotTime(times[iBestExport])})` : '') : '');
    const lastPrice = Math.max(...Object.keys(imp).map(Number));
    setNote('agile-asof', d.agile.length ? `Prices published to ${slotTime(lastPrice + 1800e3)} ${slotDay(lastPrice).toLowerCase()}` : 'No Agile prices yet');

    const lowCol = activeConfig.price?.color_low || '#4ADE80', highCol = activeConfig.price?.color_high || '#EF4444';
    const octoImp = activeConfig.octopus?.color_imp || activeConfig.theme.octo_pink, octoExp = activeConfig.octopus?.color_exp || activeConfig.theme.octo_pink;
    const plainBar = `rgba(${hexToRgbChannels(octoImp).replace(/ /g, ',')}, 0.45)`;
    const inside = (w, i) => w && i >= w.start && i <= w.end;
    const carbonColour = v => v < 100 ? activeConfig.carbon.low : v < 200 ? activeConfig.carbon.med : activeConfig.carbon.high;
    const legendItem = (text, fillStyle, strokeStyle = fillStyle, lineDash = []) => ({ text, fillStyle, strokeStyle, lineDash, lineWidth: 2, fontColor: '#D4D4D8' });

    if (agileChart) agileChart.destroy();
    agileChart = new Chart(document.getElementById('chartAgile').getContext('2d'), {
        data: {
            labels: times.map(slotTime),
            datasets: [
                { type: 'bar', label: 'Import', data: importP, yAxisID: 'price', order: 2, borderRadius: 2,
                  backgroundColor: importP.map((v, i) => v != null && v < 0 ? activeConfig.theme.brand_cyan : inside(cheap, i) ? lowCol : inside(peak, i) ? highCol : plainBar) },
                { type: 'line', label: 'Export', data: exportP, yAxisID: 'price', order: 1, borderColor: octoExp, borderDash: [4, 3], borderWidth: 1.5, pointRadius: 0 },
                { type: 'line', label: 'Carbon', data: carbonG, yAxisID: 'carbon', order: 0, borderWidth: 2, pointRadius: 0, tension: 0.3,
                  borderColor: activeConfig.carbon.med, segment: { borderColor: ctx => carbonColour((ctx.p0.parsed.y + ctx.p1.parsed.y) / 2) } }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
            plugins: {
                shadedBands: { bands: greenest ? [{ from: greenest.start, to: greenest.end, colour: activeConfig.carbon.low, label: 'Greenest' }] : [] },
                legend: { display: true, onClick: () => {}, labels: { color: '#D4D4D8', boxWidth: 18, generateLabels: () => [
                    legendItem('Import price', plainBar), legendItem('Cheapest 3 hours', lowCol), legendItem('Most expensive 3 hours', highCol),
                    legendItem('Export price', 'transparent', octoExp, [4, 3]), legendItem('Carbon forecast', 'transparent', activeConfig.carbon.med),
                    legendItem('Greenest 3 hours', `rgba(${hexToRgbChannels(activeConfig.carbon.low).replace(/ /g, ',')}, 0.25)`)] } },
                tooltip: { callbacks: {
                    title: items => `${slotDay(times[items[0].dataIndex])} ${slotTime(times[items[0].dataIndex])}`,
                    label: ctx => ctx.raw == null ? null : ctx.dataset.yAxisID === 'carbon'
                        ? `Carbon: ${Math.round(ctx.raw)} gCO₂/kWh${band[times[ctx.dataIndex]] ? ` (${band[times[ctx.dataIndex]]})` : ''}`
                        : `${ctx.dataset.label}: ${ctx.raw.toFixed(2)}p/kWh` } }
            },
            scales: {
                // A label every 3 hours (6 or 12 on narrower screens), with the day name at midnight
                x: { grid: { display: false }, ticks: { color: '#A1A1AA', autoSkip: false, maxRotation: 0, callback: function (v, i) {
                    const t = new Date(times[i]), every = this.chart.width < 450 ? 12 : this.chart.width < 700 ? 6 : 3;
                    if (t.getMinutes() || t.getHours() % every) return null;
                    return t.getHours() ? slotTime(times[i]) : t.toLocaleDateString([], { weekday: 'short' });
                } } },
                price: { position: 'left', suggestedMin: 0, grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA', callback: v => `${v}p` } },
                carbon: { position: 'right', min: 0, grid: { display: false }, ticks: { color: '#A1A1AA', callback: v => `${v} g` } }
            }
        }
    });
}

// The dot by Status in the menu: green when every data source is working, amber or red when one isn't
function loadStatusDot() {
    const dot = document.getElementById('status-dot');
    if (!dot) return;
    fetch('/api/status?summary=1').then(r => r.ok ? r.json() : null).then(d => {
        if (!d) return;
        dot.style.background = { ok: '#4ADE80', warn: '#F59E0B', fail: '#EF4444' }[d.overall];
        const failing = d.groups.flatMap(g => g.sources).filter(s => s.state === 'warn' || s.state === 'fail').map(s => s.name);
        document.getElementById('status-link').title = d.harvester.late ? 'The harvester is late' : failing.length ? `Needs a look: ${failing.join(', ')}` : 'All data sources working';
    }).catch(() => {});
}

// Run a flow line's dots backwards (end to start) or forwards
function setFlowDirection(idPrefix, reverse) {
    [1, 2].forEach(n => {
        const anim = document.getElementById(`anim-${idPrefix}-${n}`);
        if (!anim) return;
        if (reverse) { anim.setAttribute('keyPoints', '1;0'); anim.setAttribute('keyTimes', '0;1'); anim.setAttribute('calcMode', 'linear'); }
        else { anim.removeAttribute('keyPoints'); anim.removeAttribute('keyTimes'); anim.removeAttribute('calcMode'); }
    });
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
        loadFrequency();
        loadAgileForecast();
        loadStatusDot();
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
    // Highlight the card when frequency is outside the operational limits set on the admin page
    const freqOut = data.grid_frequency <= (activeConfig.frequency?.thresh_low || 49.8) || data.grid_frequency >= (activeConfig.frequency?.thresh_high || 50.2);
    const freqLimitCol = activeConfig.frequency?.color_limit || '#F6643C';
    document.getElementById('freq-val').style.color = freqOut ? freqLimitCol : '';
    document.getElementById('freq-card').style.borderColor = freqOut ? freqLimitCol : '';
    
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

    const genMix = { ...data.generation_mix };
    if (showBatteryInMix && data.battery && data.battery.discharge_mw != null) genMix['Batteries (est.)'] = data.battery.discharge_mw;
    currentTotalGW = formatGW(Object.values(genMix).reduce((a, b) => a + b, 0));
    
    const fuelColours = { "CCGT": activeConfig.fuels.ccgt, "OCG": activeConfig.fuels.ocg, "Wind": activeConfig.fuels.wind, "LV Wind": activeConfig.fuels.lv_wind || '#5FB035', "Nuclear": activeConfig.fuels.nuclear, "Biomass": activeConfig.fuels.biomass, "Hydro": activeConfig.fuels.hydro, "Pumped Storage": activeConfig.fuels.pumped_storage, "Solar": activeConfig.fuels.solar, "Other": activeConfig.fuels.other };
    fuelColours["Batteries (est.)"] = activeConfig.fuels.battery || '#A78BFA';
    const rawGenLabels = Object.keys(genMix);
    const sortedGenLabels = rawGenLabels.sort((a, b) => { let idxA = sortOrder.indexOf(a); let idxB = sortOrder.indexOf(b); if(idxA === -1) idxA = 99; if(idxB === -1) idxB = 99; return idxA - idxB; });
    const genValuesGW = sortedGenLabels.map(label => genMix[label] / 1000);
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
    // Storage nodes: pumped hydro (right) and the battery estimate (top, when switched on), each as a net flow.
    // Above zero it's releasing energy into the grid, below zero it's storing it.
    const psh_gen = Math.max(0, data.generation_mix['Pumped Storage'] || 0) / 1000;
    const psh_pump = (data.breakdown.psh_pumping_mw || 0) / 1000;
    const psh_net = psh_gen - psh_pump;
    const batt = showBatteryInMix && data.battery && data.battery.discharge_mw != null ? data.battery : null;
    const batt_out = batt ? batt.discharge_mw / 1000 : 0, batt_in = batt ? batt.charge_mw / 1000 : 0;
    const batt_net = batt_out - batt_in;
    const val_hv = (data.total_generation_mw / 1000) - val_wind - val_lv_wind - val_sol - psh_gen;
    const val_tot = val_imp + Math.max(0, val_hv) + val_wind + val_lv_wind + val_sol + Math.max(0, psh_net) + Math.max(0, batt_net);
    const val_psh = Math.abs(psh_net), val_batt = Math.abs(batt_net);
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
    // Storage nodes: direction (dots run into Total Output while discharging) and hover breakdown
    const direction = net => net > 0.005 ? 'discharging' : (net < -0.005 ? 'charging' : '');
    const tipRow = (colour, name, gw) => `<div class="flex justify-between gap-6 mb-1"><span class="font-medium" style="color: ${colour}">${name}:</span><span class="font-mono font-bold">${gw.toFixed(2)} GW</span></div>`;
    const nodeTip = (groupId, html) => {
        const group = document.getElementById(groupId);
        if (!group) return;
        group.onmouseenter = (e) => showCustomTooltip(e, html);
        group.onmousemove = moveCustomTooltip;
        group.onmouseleave = hideCustomTooltip;
    };

    const pshDir = document.getElementById('svg-dir-psh');
    if (pshDir) pshDir.textContent = psh_net > 0.005 ? 'generating' : (psh_net < -0.005 ? 'pumping' : '');
    setFlowDirection('psh', psh_net > 0);
    nodeTip('psh-node-group', `<div class="font-bold mb-1.5 border-b border-ui-grey/50 pb-1.5 text-[13px]">Pumped hydro: ${psh_net >= 0 ? 'generating' : 'pumping'} ${val_psh.toFixed(2)} GW</div>` +
        tipRow(activeConfig.fuels.pumped_storage, 'Generating', psh_gen) + tipRow(activeConfig.fuels.pumped_storage, 'Pumping', psh_pump));

    const battVal = document.getElementById('svg-val-batt');
    if (battVal) {
        const battColour = activeConfig.fuels.battery || '#A78BFA';
        battVal.textContent = batt ? val_batt.toFixed(2) + ' GW' : 'Off';
        document.getElementById('svg-dir-batt').textContent = batt ? direction(batt_net) : '';
        document.getElementById('batt-node-group').style.opacity = batt ? '' : '0.4';
        setFlowDirection('batt', batt_net > 0);
        nodeTip('batt-node-group', batt
            ? `<div class="font-bold mb-1.5 border-b border-ui-grey/50 pb-1.5 text-[13px]">Grid batteries (est.): ${batt_net >= 0 ? 'discharging' : 'charging'} ${val_batt.toFixed(2)} GW net</div>` +
              tipRow(battColour, 'Discharging', batt_out) + tipRow(battColour, 'Charging', batt_in) +
              `<div class="text-[11px] text-[#A1A1AA] mt-1">Unofficial estimate from Balancing Mechanism data</div>`
            : `<div class="font-bold text-[13px]">Grid batteries (est.)</div><div class="text-[11px] text-[#A1A1AA] mt-1">Switched off. Use the Batteries (est.) switch to show them.</div>`);
    }
    document.getElementById('svg-val-dem').textContent = Math.max(0, val_dem).toFixed(2) + ' GW';
    document.getElementById('svg-val-exp').textContent = val_exp.toFixed(2) + ' GW';

    setFlowSpeed('imp', val_imp);
    setFlowSpeed('hv', val_hv);
    setFlowSpeed('wind', val_wind + val_lv_wind);
    setFlowSpeed('sol', val_sol);
    setFlowSpeed('psh', val_psh);
    setFlowSpeed('batt', batt ? val_batt : 0);
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

    // The 5-minute frequency chart, on pages from before the full-resolution one replaced it
    if (!document.getElementById('chartFreqDetail')) {
        // nothing to draw
    } else if(chartFreqDetailInstance) {
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

    renderBatteryPanel(data, timeLabels);
    renderGasSection(data);
    renderDemandPatterns();

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

function renderBatteryPanel(data, timeLabels) {
    const netEl = document.getElementById('bess-net');
    if (!netEl || !data.battery) return;  // page or API from before the battery estimate existed

    const b = data.battery;
    const label = document.getElementById('bess-label');
    if (b.discharge_mw === null || b.charge_mw === null) {
        netEl.innerText = '---';
        label.innerText = 'No estimate available';
    } else {
        const net = (b.discharge_mw - b.charge_mw) / 1000;
        netEl.innerText = Math.abs(net).toFixed(2);
        label.innerText = `${net >= 0 ? 'Net discharging' : 'Net charging'} · Out ${(b.discharge_mw / 1000).toFixed(2)} GW · In ${(b.charge_mw / 1000).toFixed(2)} GW`;
    }

    // Net GW per row: above zero = discharging into the grid, below zero = charging. Null where there's no estimate yet.
    const series = data.history.map(h => (h.bess_discharge_mw == null || h.bess_charge_mw == null) ? null : (h.bess_discharge_mw - h.bess_charge_mw) / 1000);
    const rgba = (hex, a) => `rgba(${hexToRgbChannels(hex).replace(/ /g, ',')}, ${a})`;
    const fill = { target: 'origin', above: rgba(activeConfig.theme.tesla_green, 0.35), below: rgba(activeConfig.theme.brand_cyan, 0.35) };

    if (chartBatteryInstance) {
        chartBatteryInstance.data.labels = timeLabels;
        chartBatteryInstance.data.datasets[0].data = series;
        chartBatteryInstance.data.datasets[0].fill = fill;
        chartBatteryInstance.update();
        return;
    }
    chartBatteryInstance = new Chart(document.getElementById('chartBattery').getContext('2d'), {
        type: 'line',
        data: { labels: timeLabels, datasets: [{ label: 'Net battery flow (GW)', data: series, borderColor: '#D4D4D8', borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: fill }] },
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.raw === null ? 'No estimate' : `${ctx.raw >= 0 ? 'Discharging' : 'Charging'} ${Math.abs(ctx.raw).toFixed(2)} GW (net)` } } },
            scales: { x: { grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 8 } }, y: { suggestedMin: 0, suggestedMax: 0, grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA', callback: v => `${+v.toFixed(2)} GW` } } }
        }
    });
}

// Gas chart colours come from the 'gas' section of the config (admin page)
const GAS_SUPPLY_KEYS = { 'North Sea (UK & Norway)': 'supply_north_sea', 'Norway (Langeled)': 'supply_norway', 'LNG': 'supply_lng', 'Storage': 'supply_storage', 'Continent (BBL, IUK)': 'supply_continent' };
const GAS_DEMAND_KEYS = { 'Homes & businesses': 'demand_homes', 'Power stations': 'demand_power', 'Industry': 'demand_industry', 'Exports': 'demand_exports', 'Storage injection': 'demand_storage' };
const gasColours = keys => Object.fromEntries(Object.entries(keys).map(([label, key]) => [label, activeConfig.gas?.[key] || '#3F3F46']));
const rgbaFromHex = (hex, alpha) => `rgba(${hexToRgbChannels(hex).replace(/ /g, ',')}, ${alpha})`;

function gasBarChart(instance, canvasId, values, colours) {
    const labels = Object.keys(values).sort((a, b) => values[b] - values[a]);
    const data = labels.map(l => values[l]);
    const bg = labels.map(l => colours[l] || '#3F3F46');
    if (instance) {
        instance.data.labels = labels; instance.data.datasets[0].data = data; instance.data.datasets[0].backgroundColor = bg;
        instance.update();
        return instance;
    }
    return new Chart(document.getElementById(canvasId).getContext('2d'), {
        type: 'bar',
        data: { labels, datasets: [{ data, backgroundColor: bg, borderRadius: 5 }] },
        options: {
            responsive: true, maintainAspectRatio: false, indexAxis: 'y',
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${ctx.raw.toFixed(1)} mcm/d` } },
                datalabels: { display: true, color: '#FFFFFF', anchor: 'end', align: 'end', font: { size: 12 }, formatter: v => v.toFixed(1) } },
            layout: { padding: { right: 40 } },
            scales: { x: { beginAtZero: true, grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA' } }, y: { grid: { display: false }, ticks: { color: '#FFFFFF', font: { weight: 'bold' },
                // Split long labels over two lines (at ' (' or the first space) so they fit on narrow screens
                callback: function(v) { const l = this.getLabelForValue(v); const i = l.indexOf(' (') > 0 ? l.indexOf(' (') : (l.length > 10 ? l.indexOf(' ') : -1); return i > 0 ? [l.slice(0, i), l.slice(i + 1)] : l; } } } }
        }
    });
}

// Daily storage history for the storage sparkline and chart: fetched on load, then at most hourly
let gasStorageSeries = null, gasStorageFetchedAt = 0, sparkGasStorage, chartGasStorage;
function withGasStorageSeries(callback) {
    if (gasStorageSeries && Date.now() - gasStorageFetchedAt < 3600 * 1000) return callback(gasStorageSeries);
    fetch('/api/gas/storage').then(r => r.ok ? r.json() : null).then(d => {
        if (d && d.days && d.days.length) { gasStorageSeries = d; gasStorageFetchedAt = Date.now(); }
        if (gasStorageSeries) callback(gasStorageSeries);
    }).catch(() => {});
}

function toggleGasStorageChart() {
    const el = document.getElementById('gas-storage-expanded');
    el.classList.toggle('hidden');
    if (!el.classList.contains('hidden') && chartGasStorage) chartGasStorage.resize();
}

function renderGasStorageCharts(series, colour) {
    if (!document.getElementById('gasStorageSpark') || !document.getElementById('chartGasStorage')) return;  // page from before the storage charts existed
    const recent = series.days.length - 365;
    sparkGasStorage = buildSparkline(sparkGasStorage, 'gasStorageSpark', series.stock_gwh.slice(recent).map(v => v / 1000), series.days.slice(recent), colour, rgbaFromHex(colour, 0.1));

    // One line per year, lined up by date (a leap-year calendar gives 29 Feb a slot)
    const labels = [];
    for (let d = new Date(Date.UTC(2024, 0, 1)); d.getUTCFullYear() === 2024; d.setUTCDate(d.getUTCDate() + 1)) labels.push(d.toLocaleDateString([], { day: 'numeric', month: 'short', timeZone: 'UTC' }));
    const slot = iso => Math.round((Date.UTC(2024, +iso.slice(5, 7) - 1, +iso.slice(8, 10)) - Date.UTC(2024, 0, 1)) / 86400000);
    const byYear = {};
    series.days.forEach((day, i) => { const y = day.slice(0, 4); (byYear[y] = byYear[y] || new Array(366).fill(null))[slot(day)] = series.stock_gwh[i] / 1000; });
    const years = Object.keys(byYear).sort(), current = years[years.length - 1];
    const datasets = years.map((y, i) => ({
        label: y, data: byYear[y], spanGaps: true, pointRadius: 0, tension: 0.2, fill: false,
        borderColor: y === current ? colour : `rgba(161, 161, 170, ${(0.25 + 0.6 * i / years.length).toFixed(2)})`,
        borderWidth: y === current ? 3 : 1.5, order: y === current ? 0 : 1
    }));
    if (chartGasStorage) {
        chartGasStorage.data.datasets = datasets;
        chartGasStorage.update();
        return;
    }
    chartGasStorage = new Chart(document.getElementById('chartGasStorage').getContext('2d'), {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: true, labels: { color: '#D4D4D8', font: { family: "'Inter', sans-serif" } } },
                tooltip: { callbacks: { label: ctx => ctx.raw == null ? null : `${ctx.dataset.label}: ${ctx.raw.toFixed(1)} TWh` } } },
            scales: { x: { grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 12 } }, y: { beginAtZero: true, grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA', callback: v => v + ' TWh' } } }
        }
    });
}

function renderGasSection(data) {
    const section = document.getElementById('gas-section');
    if (!section || data.gas === undefined) return;  // page or API from before the gas section existed
    const g = data.gas;
    if (!g) { document.getElementById('gas-power-note').innerText = 'Waiting for the first gas reading.'; return; }
    const gc = activeConfig.gas || {};
    const lineSupply = gc.line_supply || '#30C5D5', lineDemand = gc.line_demand || '#F6643C', lineLinepack = gc.line_linepack || '#D4D4D8';

    const fmt = (v, dp = 1) => v == null ? '---' : v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
    document.getElementById('gas-linepack').innerText = fmt(g.linepack_mcm, 0);
    document.getElementById('gas-supply').innerText = fmt(g.supply_mcmd);
    document.getElementById('gas-demand').innerText = fmt(g.demand_mcmd);
    const balance = g.supply_mcmd - g.demand_mcmd;
    document.getElementById('gas-linepack-label').innerText = `Gas held in the pipelines · ${balance >= 0 ? 'filling' : 'emptying'} at ${fmt(Math.abs(balance))} mcm/d`;

    // Storage: % of capacity, coloured by how today's stock compares with the same date in previous years
    const st = g.storage;
    let storageColour = '#A1A1AA';
    if (st && st.capacity_gwh && document.getElementById('gas-storage-compare')) {
        document.getElementById('gas-storage').innerText = fmt(st.stock_gwh / st.capacity_gwh * 100);
        const rough = st.rough_capacity_gwh > 0 && st.rough_stock_gwh === 0 ? ' (Rough empty)' : '';
        const lng = st.lng_capacity_gwh ? ` · LNG tanks ${fmt(st.lng_stock_gwh / st.lng_capacity_gwh * 100, 0)}%` : '';
        document.getElementById('gas-storage-label').innerText = `${fmt(st.stock_gwh / 1000)} of ${fmt(st.capacity_gwh / 1000)} TWh${rough}${lng}`;
        const compareEl = document.getElementById('gas-storage-compare');
        if (st.average_gwh) {
            const ratio = st.stock_gwh / st.average_gwh * 100;
            const years = st.previous.map(p => p.year), first = Math.min(...years), last = Math.max(...years);
            storageColour = ratio < (gc.storage_thresh_low ?? 75) ? gc.storage_low : ratio < (gc.storage_thresh_high ?? 100) ? gc.storage_med : gc.storage_high;
            compareEl.innerText = `${Math.round(Math.abs(ratio - 100))}% ${ratio < 100 ? 'below' : 'above'} the ${first}–${String(last).slice(2)} average for this date` +
                (st.lowest_on_record ? ` · lowest since at least ${first}` : '');
        } else {
            compareEl.innerText = '';
        }
        compareEl.style.color = storageColour;
        document.getElementById('gas-storage').style.color = storageColour;
        document.getElementById('gas-storage-card').style.borderColor = st.average_gwh ? storageColour : '';
    }

    const stockDay = st ? ` Storage figures for gas day ${new Date(st.gas_day + 'T12:00:00Z').toLocaleDateString([], { day: 'numeric', month: 'short' })}.` : '';
    document.getElementById('gas-asof').innerText = `Source: National Gas Transmission. Flows in million m³ per day (mcm/d), latest reading ${g.flows_time} UK time.${stockDay}`;
    const stale = (Date.now() - new Date(g.updated).getTime()) > 30 * 60 * 1000;

    const pct = g.power_thermal_gw > 0 ? Math.round(g.power_electric_gw / g.power_thermal_gw * 100) : null;
    document.getElementById('gas-power-note').innerText = (stale ? '⚠ Gas data is more than 30 minutes old. ' : '') +
        `Gas for power: power stations are burning about ${fmt(g.power_thermal_gw)} GW of gas, and gas plants are generating ${fmt(g.power_electric_gw)} GW of electricity` +
        (pct ? `, so roughly ${pct}% of the gas's energy is coming out as electricity (approximate: it assumes a typical calorific value and includes CHP plants).` : '.');

    chartGasSupply = gasBarChart(chartGasSupply, 'gasSupplyChart', g.supply, gasColours(GAS_SUPPLY_KEYS));
    chartGasDemand = gasBarChart(chartGasDemand, 'gasDemandChart', g.demand, gasColours(GAS_DEMAND_KEYS));
    withGasStorageSeries(series => renderGasStorageCharts(series, storageColour));

    const labels = g.history.map(h => new Date(h.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    const lp = g.history.map(h => h.linepack_mcm), sup = g.history.map(h => h.supply_mcmd), dem = g.history.map(h => h.demand_mcmd);
    sparkGasLinepack = buildSparkline(sparkGasLinepack, 'gasLinepackSpark', lp, labels, lineLinepack, rgbaFromHex(lineLinepack, 0.1));
    sparkGasSupply = buildSparkline(sparkGasSupply, 'gasSupplySpark', sup, labels, lineSupply, rgbaFromHex(lineSupply, 0.1));
    sparkGasDemand = buildSparkline(sparkGasDemand, 'gasDemandSpark', dem, labels, lineDemand, rgbaFromHex(lineDemand, 0.1));

    const lineColours = [lineSupply, lineDemand, lineLinepack];
    if (chartGasHistory) {
        chartGasHistory.data.labels = labels;
        [sup, dem, lp].forEach((d, i) => { chartGasHistory.data.datasets[i].data = d; chartGasHistory.data.datasets[i].borderColor = lineColours[i]; });
        chartGasHistory.update();
        return;
    }
    chartGasHistory = new Chart(document.getElementById('chartGasHistory').getContext('2d'), {
        type: 'line',
        data: { labels, datasets: [
            { label: 'Supply (mcm/d)', data: sup, borderColor: lineSupply, borderWidth: 2, pointRadius: 0, tension: 0.3, yAxisID: 'y' },
            { label: 'Demand (mcm/d)', data: dem, borderColor: lineDemand, borderWidth: 2, pointRadius: 0, tension: 0.3, yAxisID: 'y' },
            { label: 'Linepack (mcm)', data: lp, borderColor: lineLinepack, borderDash: [5, 5], borderWidth: 2, pointRadius: 0, tension: 0.3, yAxisID: 'y1' }
        ] },
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: true, labels: { color: '#D4D4D8', font: { family: "'Inter', sans-serif" } } } },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#A1A1AA', maxTicksLimit: 8 } },
                y: { position: 'left', grid: { color: '#3F3F46' }, ticks: { color: '#A1A1AA' }, title: { display: true, text: 'mcm/d', color: '#A1A1AA' } },
                y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: '#D4D4D8' }, title: { display: true, text: 'Linepack (mcm)', color: '#D4D4D8' } }
            }
        }
    });
}

document.addEventListener('DOMContentLoaded', () => { updateDashboard(); setInterval(updateDashboard, 120000); });
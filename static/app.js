let lastResponse = null;
let activeTab = 'table';

const form = document.querySelector('#calc-form');
const statusEl = document.querySelector('#status');
const logCard = document.querySelector('#log-card');
const logOutput = document.querySelector('#log-output');
const results = document.querySelector('#results');
const table = document.querySelector('#result-table');
const dataKind = document.querySelector('#data-kind');
const tableStride = document.querySelector('#table-stride');
const selectedPlotTitle = document.querySelector('#plot-selected-title');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = document.querySelector('#calculate-btn');
  setStatus('Расчет выполняется…', 'busy');
  button.disabled = true;

  try {
    const response = await fetch('/api/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(readPayload()),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(formatApiError(payload));
    }
    lastResponse = payload;
    renderResults(payload);
    setStatus('Расчет завершен', 'success');
  } catch (error) {
    console.error(error);
    setStatus('Ошибка', 'error');
    logCard.classList.remove('hidden');
    logOutput.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll('.tab').forEach((button) => {
  button.addEventListener('click', () => {
    activeTab = button.dataset.tab;
    activateTab(activeTab);
    if (lastResponse) {
      setTimeout(() => resizeVisiblePlots(), 0);
    }
  });
});

dataKind.addEventListener('change', () => {
  if (lastResponse) {
    renderTable(lastResponse);
    renderSelectedPlot(lastResponse);
  }
});

tableStride.addEventListener('change', () => {
  if (lastResponse) renderTable(lastResponse);
});

window.addEventListener('resize', () => resizeVisiblePlots());

function readPayload() {
  const data = new FormData(form);
  return {
    binary_path: data.get('binary_path'),
    rectangle: {
      a: Number(data.get('a')),
      b: Number(data.get('b')),
      c: Number(data.get('c')),
      d: Number(data.get('d')),
    },
    grid: {
      n: Number(data.get('n')),
      m: Number(data.get('m')),
    },
    variant: Number(data.get('variant')),
    base: {
      omega: Number(data.get('base_omega')),
      epsilon_mem: Number(data.get('base_epsilon')),
      max_iterations: Number(data.get('base_max_iterations')),
    },
    fine: {
      omega: Number(data.get('fine_omega')),
      epsilon_mem: Number(data.get('fine_epsilon')),
      max_iterations: Number(data.get('fine_max_iterations')),
    },
  };
}

function renderResults(response) {
  logCard.classList.remove('hidden');
  results.classList.remove('hidden');
  logOutput.textContent = response.log;
  renderTable(response);
  renderPlots(response);
}

function renderTable(response) {
  const kind = dataKind.value;
  const stride = Number(tableStride.value);
  const n = Number(response.base.grid.n);
  const m = Number(response.base.grid.m);
  const nodesByIndex = new Map(response.nodes.map((node) => [`${node.i}:${node.j}`, node]));
  const xIndices = sampleIndices(n, stride);
  const yIndices = sampleIndices(m, stride);

  const theadRows = [
    `<tr><th class="corner">j / i</th>${xIndices.map((i) => `<th>i=${i}</th>`).join('')}</tr>`,
    `<tr><th>x<sub>i</sub></th>${xIndices.map((i) => `<th>${formatNumber(nodesByIndex.get(`${i}:0`).x, 6)}</th>`).join('')}</tr>`,
  ];

  const bodyRows = yIndices.map((j) => {
    const y = nodesByIndex.get(`0:${j}`).y;
    const cells = xIndices.map((i) => {
      const node = nodesByIndex.get(`${i}:${j}`);
      return `<td title="i=${i}, j=${j}, x=${node.x}, y=${node.y}">${formatNumber(node[kind], 10)}</td>`;
    }).join('');
    return `<tr><th>j=${j}<br><span>y=${formatNumber(y, 6)}</span></th>${cells}</tr>`;
  });

  table.innerHTML = `<thead>${theadRows.join('')}</thead><tbody>${bodyRows.join('')}</tbody>`;
}

function renderPlots(response) {
  drawPlot('plot-initial-base', response.plots.initial_base);
  drawPlot('plot-initial-fine', response.plots.initial_fine);
  drawPlot('plot-solution-base', response.plots.solution_base);
  drawPlot('plot-solution-fine', response.plots.solution_fine);
  drawPlot('plot-difference', response.plots.difference);
  renderSelectedPlot(response);
}

function renderSelectedPlot(response) {
  const plotByKind = {
    base: ['solution_base', 'v⁽ᴺ⁾ — основная сетка'],
    fine: ['solution_fine', 'v₂⁽ᴺ²⁾ — половинная сетка на общих узлах'],
    difference: ['difference', 'v⁽ᴺ⁾ − v₂⁽ᴺ²⁾'],
  };
  const [plotKey, title] = plotByKind[dataKind.value];
  selectedPlotTitle.textContent = title;
  drawPlot('plot-selected', response.plots[plotKey]);
  if (activeTab === 'difference') {
    drawPlot('plot-difference', response.plots.difference);
  }
}

function drawPlot(elementId, figureJson) {
  const figure = JSON.parse(figureJson);
  Plotly.react(elementId, figure.data, figure.layout, {
    responsive: true,
    scrollZoom: true,
    displaylogo: false,
  });
}

function activateTab(name) {
  document.querySelectorAll('.tab').forEach((button) => {
    button.classList.toggle('active', button.dataset.tab === name);
  });
  document.querySelectorAll('.tab-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id === `panel-${name}`);
  });
}

function resizeVisiblePlots() {
  document.querySelectorAll('.tab-panel.active .plot').forEach((plot) => Plotly.Plots.resize(plot));
}

function sampleIndices(maxIndex, stride) {
  const indices = [];
  for (let i = 0; i <= maxIndex; i += stride) indices.push(i);
  if (indices[indices.length - 1] !== maxIndex) indices.push(maxIndex);
  return indices;
}

function formatNumber(value, digits) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return number.toExponential(digits);
}

function formatApiError(payload) {
  if (payload && typeof payload.detail === 'string') return payload.detail;
  return JSON.stringify(payload, null, 2);
}

function setStatus(message, kind) {
  statusEl.textContent = message;
  statusEl.className = `status ${kind}`;
}

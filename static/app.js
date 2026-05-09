// =====================================================================
// EEM Fingerprint Web Frontend
// =====================================================================
const API = '';   // 同源
const $  = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => Array.from(root.querySelectorAll(s));

const STATE = {
  blank: null,           // File
  sample: null,          // File
  session_id: null,
  result: null,          // {raw, corrected, fingerprint}
  view: 'contour',
  fillMode: 'fill',
  // 比对页
  cmp: { a_blank:null, a_sample:null, b_blank:null, b_sample:null,
         a_session:null, b_session:null },
  // 检索页
  searchResults: [],
  // FRI 区域中文名 (启动时从后端拉取)
  friNamesCN: {
    "I_Tyrosine":     "Ⅰ 类酪氨酸",
    "II_Tryptophan":  "Ⅱ 类色氨酸",
    "III_FulvicAcid": "Ⅲ 类富里酸",
    "IV_SMP":         "Ⅳ 溶解性微生物代谢产物",
    "V_HumicAcid":    "Ⅴ 类腐殖酸",
  },
};

// 颜色: 与 CSS 风格一致
const COLORSCALE = [
  [0.0, '#0a0f1f'], [0.2, '#0a3a6e'], [0.4, '#0875b0'],
  [0.55,'#19c3ff'], [0.7, '#5fffaf'], [0.85,'#ffd24a'], [1.0, '#ff5cf7']
];

const PLOT_LAYOUT_BASE = {
  paper_bgcolor: 'rgba(11,20,40,0.0)',
  plot_bgcolor:  'rgba(6,11,24,0.4)',
  font: { family: 'JetBrains Mono, Consolas, monospace',
          color: '#d6e8ff', size: 11 },
  margin: { l: 60, r: 30, t: 36, b: 50 },
  xaxis: { title: 'Emission λ (nm)', gridcolor: 'rgba(76,232,255,0.1)',
           zerolinecolor: 'rgba(76,232,255,0.2)' },
  yaxis: { title: 'Excitation λ (nm)', gridcolor: 'rgba(76,232,255,0.1)',
           zerolinecolor: 'rgba(76,232,255,0.2)' },
};
const PLOT_CONFIG = { displayModeBar: true, displaylogo: false,
                      modeBarButtonsToRemove: ['lasso2d','select2d'],
                      toImageButtonOptions: { format: 'png',
                          bgcolor: '#060B18', filename: 'eem' } };

// ---------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------
$$('.tab').forEach(b => b.addEventListener('click', () => {
  $$('.tab').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  const target = b.dataset.page;
  $$('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + target));
  if (target === 'library') refreshLibrary();
}));

// ---------------------------------------------------------------------
// 文件上传 (Drag & drop + Click)
// ---------------------------------------------------------------------
function bindUpload(zoneSel, inputSel, fnSel, key, scope=STATE) {
  const zone = $(zoneSel), input = $(inputSel), fn = $(fnSel);
  const setFile = f => {
    if (!f) return;
    if (key.includes('.')) {
      const [a,b] = key.split('.'); scope[a][b] = f;
    } else { scope[key] = f; }
    fn.textContent = f.name;
  };
  zone.addEventListener('click', e => {
    if (e.target.tagName === 'INPUT') return;
    input.click();
  });
  input.addEventListener('change', e => setFile(e.target.files[0]));
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('dragover');
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  });
}
bindUpload('#up-blank',    '#file-blank',    '#fn-blank',    'blank');
bindUpload('#up-sample',   '#file-sample',   '#fn-sample',   'sample');
bindUpload('#up-a-blank',  '#file-a-blank',  '#fn-a-blank',  'cmp.a_blank');
bindUpload('#up-a-sample', '#file-a-sample', '#fn-a-sample', 'cmp.a_sample');
bindUpload('#up-b-blank',  '#file-b-blank',  '#fn-b-blank',  'cmp.b_blank');
bindUpload('#up-b-sample', '#file-b-sample', '#fn-b-sample', 'cmp.b_sample');

// ---------------------------------------------------------------------
// Toast & Loader
// ---------------------------------------------------------------------
function toast(msg, isErr=false) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.toggle('error', isErr);
  t.classList.add('show');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2500);
}
function setLoading(on, text='PROCESSING EEM...') {
  $('#loader').classList.toggle('show', on);
  $('#loader .loader-text').textContent = '▶ ' + text;
}
function setStatus(s) { $('#bar-status').textContent = s; }
function setSession(s) { $('#bar-session').textContent = 'SESSION: ' + (s ? s.slice(0,12) + '…' : '--'); }

// ---------------------------------------------------------------------
// Run pipeline
// ---------------------------------------------------------------------
$('#btn-run').addEventListener('click', async () => {
  if (!STATE.blank || !STATE.sample) {
    toast('请先选择 blank 与 sample CSV', true); return;
  }
  setLoading(true, 'PROCESSING EEM...');
  setStatus('PROCESSING...');
  try {
    const fd = new FormData();
    fd.append('blank',  STATE.blank);
    fd.append('sample', STATE.sample);
    fd.append('agg_method',    $('#p-agg').value);
    fd.append('em_min',        $('#p-em-min').value);
    fd.append('em_max',        $('#p-em-max').value);
    fd.append('ex_keep_below', $('#p-ex-keep').value);
    fd.append('rayleigh_band', $('#p-ray').value);
    fd.append('raman_band',    $('#p-raman').value);
    fd.append('sg_window',     $('#p-sgw').value);
    fd.append('sg_poly',       $('#p-sgp').value);
    const r = await fetch(API + '/api/process', { method: 'POST', body: fd });
    if (!r.ok) {
      const err = await r.json().catch(()=>({detail:'unknown'}));
      throw new Error(err.detail || r.statusText);
    }
    STATE.result = await r.json();
    STATE.session_id = STATE.result.session_id;
    setSession(STATE.session_id);
    renderAll();
    $('#btn-add').disabled = false;
    toast('处理完成,特征已提取');
    setStatus('READY · ' + STATE.result.corrected.shape.join('×'));
  } catch (e) {
    toast('处理失败: ' + e.message, true);
    setStatus('ERROR');
  } finally {
    setLoading(false);
  }
});

// ---------------------------------------------------------------------
// View tabs (Tab1 内的子视图)
// ---------------------------------------------------------------------
$$('.view-tab').forEach(b => b.addEventListener('click', () => {
  $$('.view-tab').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  STATE.view = b.dataset.view;
  $('#fill-ctrl').style.display = (STATE.view === 'contour' || STATE.view === 'raw') ? '' : 'none';
  drawMain();
}));
$('#sel-fill').addEventListener('change', e => {
  STATE.fillMode = e.target.value;
  drawMain();
});

// ---------------------------------------------------------------------
// 渲染
// ---------------------------------------------------------------------
function makeContour(eem, title, fill='fill') {
  const trace = {
    type: fill === 'fill' ? 'contour' : 'contour',
    z: eem.z, x: eem.em, y: eem.ex,
    colorscale: COLORSCALE,
    contours: { coloring: fill === 'fill' ? 'fill' : 'lines',
                showlabels: fill === 'lines',
                labelfont: { color: '#d6e8ff', size: 9 } },
    line: { width: fill === 'lines' ? 0.8 : 0.4,
            color: fill === 'lines' ? '#4ce8ff' : null },
    showscale: fill === 'fill',
    colorbar: { thickness: 12, tickfont: { color:'#8aa2c8', size:10 },
                outlinewidth: 0 },
    ncontours: 24,
  };
  const layout = Object.assign({}, PLOT_LAYOUT_BASE,
    { title: { text: title, font: { color: '#4ce8ff', size: 12 } } });
  return [[trace], layout];
}

function makePcolor(eem, title) {
  const trace = {
    type: 'heatmap',
    z: eem.z, x: eem.em, y: eem.ex,
    colorscale: COLORSCALE,
    colorbar: { thickness: 12, tickfont: { color:'#8aa2c8', size:10 },
                outlinewidth: 0 },
  };
  const layout = Object.assign({}, PLOT_LAYOUT_BASE,
    { title: { text: title, font: { color: '#4ce8ff', size: 12 } } });
  return [[trace], layout];
}

function friLabel(key) {
  return STATE.friNamesCN[key] || key;
}

function makeFRIBar(fri) {
  const keys = Object.keys(fri);
  const labels = keys.map(friLabel);
  const vals = keys.map(k => fri[k]);
  const colors = ['#4C72B0','#55A868','#C44E52','#8172B2','#CCB974'];
  const trace = {
    type: 'bar', x: labels, y: vals,
    marker: { color: colors.slice(0, keys.length),
              line: { color: '#4ce8ff', width: 0.5 } },
    text: vals.map(v => (v*100).toFixed(1) + '%'),
    textposition: 'outside', textfont: { color: '#d6e8ff' },
    hovertext: keys.map((k, i) => `${k}<br>${labels[i]}<br>占比: ${(vals[i]*100).toFixed(2)}%`),
    hoverinfo: 'text',
  };
  const layout = Object.assign({}, PLOT_LAYOUT_BASE, {
    title: { text: 'FRI 五区域组成 / Composition', font: { color:'#4ce8ff', size: 12 } },
    xaxis: { tickangle: -20, gridcolor: 'transparent', tickfont: { size: 10 } },
    yaxis: { title: '占比 Fraction', range: [0, Math.max(1.0, ...vals) * 1.15] },
    margin: { l: 60, r: 30, t: 36, b: 110 },
  });
  return [[trace], layout];
}

function drawMain() {
  if (!STATE.result) return;
  const r = STATE.result;
  let data, layout;
  if (STATE.view === 'contour') {
    [data, layout] = makeContour(r.corrected, 'Sample EEM (corrected)', STATE.fillMode);
  } else if (STATE.view === 'pcolor') {
    [data, layout] = makePcolor(r.corrected, 'Sample EEM (pcolor)');
  } else if (STATE.view === 'raw') {
    [data, layout] = makeContour(r.raw, 'Sample EEM (raw)', STATE.fillMode);
  } else {
    [data, layout] = makeFRIBar(r.fingerprint.fri_fractions);
  }
  Plotly.react('plot', data, layout, PLOT_CONFIG);
}

function renderTables(fp) {
  // FRI (英文 key + 中文标注)
  const friBody = $('#tbl-fri').querySelector('tbody');
  friBody.innerHTML = '<tr><th>区域</th><th>体积</th><th>占比</th></tr>' +
    Object.keys(fp.fri_volumes).map(k => `
      <tr title="${esc(k)}">
        <td>${esc(friLabel(k))}</td>
        <td>${fp.fri_volumes[k].toExponential(2)}</td>
        <td>${(fp.fri_fractions[k]*100).toFixed(2)}%</td>
      </tr>`).join('');
  // Peaks
  const pkBody = $('#tbl-peaks').querySelector('tbody');
  pkBody.innerHTML = '<tr><th>#</th><th>Ex</th><th>Em</th><th>I</th></tr>' +
    fp.peaks.map((p,i) => `
      <tr><td>${i+1}</td><td>${p.ex.toFixed(1)}</td>
          <td>${p.em.toFixed(1)}</td><td>${p.intensity.toExponential(2)}</td></tr>`).join('');
  // Stats
  const stBody = $('#tbl-stats').querySelector('tbody');
  stBody.innerHTML = '<tr><th>指标</th><th>数值</th></tr>' +
    Object.keys(fp.stats).map(k => `
      <tr><td>${k}</td><td>${Number(fp.stats[k]).toPrecision(4)}</td></tr>`).join('');
}

function renderAll() {
  drawMain();
  renderTables(STATE.result.fingerprint);
}

// ---------------------------------------------------------------------
// 入库
// ---------------------------------------------------------------------
$('#btn-add').addEventListener('click', async () => {
  if (!STATE.session_id) return;
  const name = prompt('指纹名称:', (STATE.sample && STATE.sample.name.replace(/\.csv$/,'')) || 'sample');
  if (!name) return;
  const category = prompt('类别 (可选: 工业废水/生活污水/雨水/地表水):', '') || '';
  const note = prompt('备注 (可选):', '') || '';
  try {
    const r = await fetch(API + '/api/library/add', {
      method: 'POST', headers: { 'Content-Type':'application/json' },
      body: JSON.stringify({
        session_id: STATE.session_id, name, category, note })
    });
    if (!r.ok) throw new Error((await r.json()).detail);
    toast('已入库');
  } catch (e) { toast('入库失败: ' + e.message, true); }
});

// ---------------------------------------------------------------------
// 库管理
// ---------------------------------------------------------------------
async function refreshLibrary() {
  try {
    const r = await fetch(API + '/api/library/list');
    const d = await r.json();
    const tb = $('#lib-table tbody');
    if (!d.items.length) {
      tb.innerHTML = '<tr><td colspan="7" class="empty">— 库为空 —</td></tr>';
    } else {
      tb.innerHTML = d.items.map(it => `
        <tr data-id="${it.id}">
          <td>${it.id}</td><td>${esc(it.name)}</td>
          <td>${esc(it.category||'')}</td>
          <td>${esc(it.source_file||'')}</td>
          <td>${esc(it.blank_file||'')}</td>
          <td>${esc(it.created_at||'')}</td>
          <td>${esc(it.note||'')}</td>
        </tr>`).join('');
      tb.querySelectorAll('tr').forEach(tr => tr.addEventListener('click', () => {
        tb.querySelectorAll('tr').forEach(t => t.classList.remove('sel'));
        tr.classList.add('sel');
      }));
    }
    $('#lib-stat').textContent = `条目数: ${d.total}`;
  } catch (e) { toast('刷新失败: ' + e.message, true); }
}
$('#btn-lib-refresh').addEventListener('click', refreshLibrary);
$('#btn-lib-delete').addEventListener('click', async () => {
  const sel = $('#lib-table tbody tr.sel');
  if (!sel) { toast('请先选中一行', true); return; }
  if (!confirm('确认删除条目 ID=' + sel.dataset.id + '?')) return;
  await fetch(API + '/api/library/' + sel.dataset.id, { method: 'DELETE' });
  refreshLibrary();
});

function esc(s) { return String(s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// ---------------------------------------------------------------------
// 检索
// ---------------------------------------------------------------------
$('#btn-search').addEventListener('click', async () => {
  if (!STATE.session_id) { toast('请先在 [01] 运行预处理', true); return; }
  setLoading(true, 'SEARCHING...');
  try {
    const r = await fetch(API + '/api/library/search', {
      method:'POST', headers: { 'Content-Type':'application/json' },
      body: JSON.stringify({
        session_id: STATE.session_id,
        top_k: parseInt($('#s-topk').value)||10,
        cosine_weight: parseFloat($('#s-wcos').value)||0.6,
        euclid_weight: parseFloat($('#s-weu').value)||0.4,
      })
    });
    if (!r.ok) throw new Error((await r.json()).detail);
    const d = await r.json();
    STATE.searchResults = d.results;
    const tb = $('#search-table tbody');
    tb.innerHTML = d.results.length === 0
      ? '<tr><td colspan="7" class="empty">— 库为空,先入库几条指纹 —</td></tr>'
      : d.results.map((row, i) => `
        <tr data-i="${i}">
          <td>${i+1}</td><td>${row.id}</td>
          <td>${esc(row.name)}</td><td>${esc(row.category||'')}</td>
          <td>${row.metrics.cosine_similarity.toFixed(4)}</td>
          <td>${row.metrics.euclidean_distance.toFixed(4)}</td>
          <td>${row.metrics.score.toFixed(4)}</td>
        </tr>`).join('');
    tb.querySelectorAll('tr').forEach(tr => tr.addEventListener('click', () => {
      tb.querySelectorAll('tr').forEach(t => t.classList.remove('sel'));
      tr.classList.add('sel');
      const idx = parseInt(tr.dataset.i);
      drawSearchPair(idx);
    }));
    if (d.results.length) drawSearchPair(0);
    $('#search-stat').textContent = `找到 ${d.results.length} 条`;
  } catch (e) { toast('检索失败: ' + e.message, true); }
  finally { setLoading(false); }
});

function drawSearchPair(idx) {
  const cand = STATE.searchResults[idx];
  if (!STATE.result) return;
  // 查询: 当前 corrected EEM
  const [d1,l1] = makeContour(STATE.result.corrected, 'Query', 'fill');
  Plotly.react('plot-q', d1, l1, PLOT_CONFIG);
  // 候选
  const eem = { ex: cand.ex, em: cand.em, z: cand.z };
  const [d2,l2] = makeContour(eem, `#${cand.id} ${cand.name}`, 'fill');
  Plotly.react('plot-c', d2, l2, PLOT_CONFIG);
}

// ---------------------------------------------------------------------
// 比对页
// ---------------------------------------------------------------------
async function processOne(blank, sample) {
  const fd = new FormData();
  fd.append('blank', blank); fd.append('sample', sample);
  fd.append('agg_method', $('#p-agg').value);
  fd.append('em_min', $('#p-em-min').value);
  fd.append('em_max', $('#p-em-max').value);
  fd.append('ex_keep_below', $('#p-ex-keep').value);
  fd.append('rayleigh_band', $('#p-ray').value);
  fd.append('raman_band', $('#p-raman').value);
  fd.append('sg_window', $('#p-sgw').value);
  fd.append('sg_poly', $('#p-sgp').value);
  const r = await fetch(API + '/api/process', { method: 'POST', body: fd });
  if (!r.ok) throw new Error((await r.json()).detail);
  return r.json();
}

$('#btn-compare').addEventListener('click', async () => {
  const c = STATE.cmp;
  if (!c.a_blank || !c.a_sample || !c.b_blank || !c.b_sample) {
    toast('A、B 各自的 blank 与 sample 都要选', true); return;
  }
  setLoading(true, 'COMPARING...');
  try {
    const ra = await processOne(c.a_blank, c.a_sample);
    const rb = await processOne(c.b_blank, c.b_sample);
    c.a_session = ra.session_id; c.b_session = rb.session_id;
    const r = await fetch(API + '/api/compare', {
      method:'POST', headers: { 'Content-Type':'application/json' },
      body: JSON.stringify({ session_a: ra.session_id, session_b: rb.session_id })
    });
    if (!r.ok) throw new Error((await r.json()).detail);
    const d = await r.json();
    $('#compare-result').style.display = '';
    $('#cmp-score').textContent = d.score.toFixed(4);
    $('#cmp-cos').textContent  = d.cosine_similarity.toFixed(4);
    $('#cmp-eu').textContent   = d.euclidean_distance.toFixed(4);
    const [da,la] = makeContour(d.a.corrected, 'Sample A: ' + d.a.name, 'fill');
    const [db,lb] = makeContour(d.b.corrected, 'Sample B: ' + d.b.name, 'fill');
    Plotly.react('plot-cmp-a', da, la, PLOT_CONFIG);
    Plotly.react('plot-cmp-b', db, lb, PLOT_CONFIG);
  } catch (e) { toast('比对失败: ' + e.message, true); }
  finally { setLoading(false); }
});

// ---------------------------------------------------------------------
// 初始
// ---------------------------------------------------------------------
setStatus('SYSTEM READY');
fetch(API + '/api/health').then(r => r.json()).then(d => {
  setStatus(`READY · LIB=${d.library_count}`);
}).catch(() => setStatus('OFFLINE'));

// 拉取 FRI 区域中文名 (覆盖默认 fallback)
fetch(API + '/api/fri/regions').then(r => r.json()).then(d => {
  if (d.regions) {
    d.regions.forEach(reg => { STATE.friNamesCN[reg.key] = reg.name_cn; });
  }
}).catch(() => {});

const report = window.jevReport;
const arms = [
  { id: 'rules', name: 'Regras', short: 'R' },
  { id: 'ollama', name: 'Qwen local', short: 'Q' },
  { id: 'jev', name: 'Jev direto', short: 'J' },
  { id: 'gate', name: 'Jev + gate', short: 'G' }
];
const routeNames = { delivery: 'Entrega', billing: 'Cobrança', technical: 'Técnico', manual: 'Revisão manual' };
const state = { category: 'all', language: 'all', effect: 'all', search: '', selected: null };
const $ = id => document.getElementById(id);
const make = (tag, className, value) => {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (value !== undefined) item.textContent = value;
  return item;
};
const result = (item, arm) => item.predictions[arm];
const routeRight = (item, arm) => result(item, arm).route === item.expected.route;
const reviewRight = (item, arm) => result(item, arm).review === item.expected.review;
const jointRight = (item, arm) => routeRight(item, arm) && reviewRight(item, arm);
const count = value => Math.round(value * 24);
const percent = value => Math.round(value * 100) + '%';
const reviewText = value => value ? 'sim' : 'não';
function effect(item) {
  if (!jointRight(item, 'jev') && jointRight(item, 'gate')) return 'improved';
  if (jointRight(item, 'jev') && !jointRight(item, 'gate')) return 'regressed';
  if (result(item, 'gate').path === 'jev_to_ollama') return 'fallback';
  return 'retained';
}
function effectLabel(item) {
  const labels = { improved: 'Gate corrigiu', regressed: 'Gate piorou', fallback: 'Fallback ao LLM', retained: 'Jev conservado' };
  return labels[effect(item)];
}
function renderOverview() {
  const cards = $('scorecards');
  const chart = $('dimension-chart');
  const operations = $('operations-table');
  for (const arm of arms) {
    const summary = report.comparison[arm.id === 'gate' ? 'jev_gate-test' : arm.id + '-test'];
    const card = make('article', 'scorecard' + (arm.id === 'jev' ? ' chosen' : ''));
    const title = make('div', 'score-title');
    title.append(make('span', 'score-index', arm.short), make('h3', '', arm.name));
    const number = make('strong', 'score-number', String(count(summary.joint_accuracy)));
    number.append(make('small', '', ' / 24'));
    card.append(title, number, make('p', '', 'rota ' + count(summary.route_accuracy) + '/24  ·  revisão ' + count(summary.review_accuracy) + '/24'));
    cards.append(card);

    const group = make('div', 'dimension-group');
    group.append(make('span', 'dimension-name', arm.name));
    for (const [key, label] of [['route_accuracy', 'Rota'], ['review_accuracy', 'Revisão'], ['joint_accuracy', 'Ambas']]) {
      const row = make('div', 'dimension-row');
      row.append(make('span', '', label));
      const track = make('div', 'dimension-track'), fill = make('div', 'dimension-fill ' + arm.id);
      fill.style.width = percent(summary[key]);
      track.append(fill);
      row.append(track, make('strong', '', count(summary[key]) + '/24'));
      group.append(row);
    }
    chart.append(group);
  }
  const table = make('table');
  const thead = make('thead'), heading = make('tr');
  for (const label of ['Motor', 'p50', 'p95', 'Jev tokens']) heading.append(make('th', '', label));
  thead.append(heading); table.append(thead);
  const tbody = make('tbody');
  for (const arm of arms) {
    const s = report.comparison[arm.id === 'gate' ? 'jev_gate-test' : arm.id + '-test'];
    const row = make('tr');
    for (const value of [arm.name, Math.round(s.latency_p50_ms) + ' ms', Math.round(s.latency_p95_ms) + ' ms', s.jev_input_tokens.toLocaleString('pt-BR')]) row.append(make('td', '', value));
    tbody.append(row);
  }
  table.append(tbody); operations.append(table);
  const t = report.thresholds;
  $('gate-rule').textContent = 'Conservar se P(rota escolhida) ≥ ' + t.route_min_probability.toFixed(2).replace('.', ',') + ' e (P(revisão) ≤ ' + t.review_endpoint_margin.toFixed(2).replace('.', ',') + ' ou ≥ ' + (1 - t.review_endpoint_margin).toFixed(2).replace('.', ',') + ').';
}
function renderCategories() {
  const host = $('category-breakdown');
  for (const category of ['Rota direta', 'Poucos detalhes', 'Duas equipes', 'Instrução no texto']) {
    const cases = report.cases.filter(item => item.category === category);
    const row = make('div', 'category-row');
    row.append(make('strong', '', category), make('span', '', cases.length + ' casos'));
    for (const arm of arms) row.append(make('span', '', arm.short + ' ' + cases.filter(item => jointRight(item, arm.id)).length + '/' + cases.length));
    host.append(row);
  }
}function fillCategories() {
  const categories = [...new Set(report.cases.map(item => item.category))];
  for (const category of ['Rota direta', 'Poucos detalhes', 'Duas equipes', 'Instrução no texto']) {
    if (categories.includes(category)) {
      const option = make('option', '', category);
      option.value = category;
      $('category-filter').append(option);
    }
  }
}
function detail(item) {
  const host = $('case-detail'); host.replaceChildren();
  if (!item) { host.append(make('p', 'empty', 'Nenhum caso corresponde aos filtros.')); return; }
  const heading = make('div', 'detail-heading');
  heading.append(make('span', 'detail-id', item.id + ' / ' + item.language.toUpperCase()), make('span', 'effect-pill ' + effect(item), effectLabel(item)));
  host.append(heading, make('h3', '', item.message));
  const expected = make('div', 'expected');
  expected.append(make('span', '', 'RÓTULO ESPERADO'), make('strong', '', routeNames[item.expected.route]), make('span', '', 'Revisão humana: ' + reviewText(item.expected.review)));
  host.append(expected);
  const grid = make('div', 'prediction-grid');
  for (const arm of arms) {
    const p = result(item, arm.id), card = make('article', 'prediction ' + (jointRight(item, arm.id) ? 'right' : 'wrong'));
    const header = make('div', 'prediction-head');
    header.append(make('strong', '', arm.name), make('span', '', jointRight(item, arm.id) ? 'ambas certas' : 'erro'));
    card.append(header);
    const line = make('div', 'prediction-values');
    line.append(make('span', routeRight(item, arm.id) ? '' : 'mismatch', routeNames[p.route]), make('span', reviewRight(item, arm.id) ? '' : 'mismatch', 'Revisão ' + reviewText(p.review)));
    card.append(line);
    if (arm.id === 'jev') {
      const probability = p.route_probs?.[p.route];
      card.append(make('p', 'prediction-note', 'P(rota) ' + (probability === undefined ? '—' : percent(probability)) + ' · confiança ' + (p.route_confidence === null ? '—' : percent(p.route_confidence)) + ' · P(revisão) ' + (p.review_probability === null ? '—' : percent(p.review_probability))));
    }
    if (arm.id === 'gate') card.append(make('p', 'prediction-note', p.path === 'jev_to_ollama' ? 'Saída do Qwen substituiu a decisão Jev' : 'Decisão Jev conservada'));
    grid.append(card);
  }
  host.append(grid);
  host.append(make('p', 'detail-foot', 'Valores destacados divergem do rótulo esperado. As probabilidades exibidas são da chamada Jev direto. O gate fez outra chamada Jev; não infira seu caminho a partir destes valores.'));
}
function visibleCases() {
  const search = state.search.toLocaleLowerCase('pt-BR');
  return report.cases.filter(item =>
    (state.category === 'all' || item.category === state.category) &&
    (state.language === 'all' || item.language === state.language) &&
    (state.effect === 'all' ||
      (state.effect === 'jev_error' ? !jointRight(item, 'jev') :
        state.effect === 'fallback' ? result(item, 'gate').path === 'jev_to_ollama' : effect(item) === state.effect)) &&
    (!search || item.id.toLocaleLowerCase('pt-BR').includes(search) || item.message.toLocaleLowerCase('pt-BR').includes(search))
  );
}
function renderCases() {
  const visible = visibleCases();
  $('case-count').textContent = visible.length + ' de 24 casos';
  if (!visible.some(item => item.id === state.selected)) state.selected = visible[0]?.id || null;
  const host = $('case-list'); host.replaceChildren();
  for (const item of visible) {
    const button = make('button', 'case-row' + (state.selected === item.id ? ' active' : ''));
    button.type = 'button';
    button.setAttribute('aria-pressed', String(state.selected === item.id));
    const top = make('div', 'case-top');
    top.append(make('strong', '', item.id), make('span', 'case-category', item.category));
    button.append(top, make('p', '', item.message), make('span', 'case-outcome ' + effect(item), effectLabel(item)));
    button.addEventListener('click', () => {
      state.selected = item.id; renderCases();
      if (window.innerWidth < 800) $('case-detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    host.append(button);
  }
  detail(visible.find(item => item.id === state.selected));
}
for (const [id, key, event] of [
  ['category-filter', 'category', 'change'],
  ['language-filter', 'language', 'change'],
  ['effect-filter', 'effect', 'change'],
  ['case-search', 'search', 'input']
]) $(id).addEventListener(event, e => { state[key] = e.target.value.trim(); renderCases(); });
fillCategories(); renderOverview(); renderCategories(); renderCases();

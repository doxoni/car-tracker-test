// -*- coding: utf-8 -*-
/* Car Tracker — Telegram Mini App SPA
   Features: auth via initData, fleet list, expenses, dashboard + charts,
              fuel barrels (read), analytics, Telegram theme support.

   Экраны: дашборд, фуры, расходы, бочки, отчёты. Каждая вкладка - свой
   блок внутри #app-main, переключение идёт функцией showTab().
*/

(() => {
  "use strict";

  // ------------------------------------------------------------
  // Telegram Web App init
  // ------------------------------------------------------------
  // Если страницу открыли в обычном браузере (без Telegram), объекта
  // WebApp может не быть - тогда приложение должно показать понятное
  // сообщение, а не падать с ошибкой.
  const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : {
    initData: '',
    expand() {},
    setHeaderColor() {},
    showAlert(msg) { alert(msg); },
    MainButton: { setText() {}, onClick() {}, show() {}, hide() {}, data: {} },
    BackButton: { onClick() {} }
  };
  tg.expand();

  const root = document.documentElement;

  // ------------------------------------------------------------
  // Тема Telegram
  // ------------------------------------------------------------
  // Разбирает цвет Telegram: «#rrggbb», «rgb(r, g, b)» или «rgba(r, g, b, a)».
  function parseColor(value) {
    if (!value) return null;
    const text = String(value).trim();
    let match = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (match) {
      let hex = match[1];
      if (hex.length === 3) {
        hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
      }
      return [
        parseInt(hex.slice(0, 2), 16),
        parseInt(hex.slice(2, 4), 16),
        parseInt(hex.slice(4, 6), 16)
      ];
    }
    match = text.match(/^rgba?\(([^)]+)\)$/i);
    if (match) {
      const parts = match[1].split(/[,\s/]+/).filter(Boolean).map(Number);
      if (parts.length >= 3 && parts.slice(0, 3).every(n => !isNaN(n))) {
        return [parts[0], parts[1], parts[2]];
      }
    }
    return null;
  }

  // Тот же цвет с прозрачностью.
  function withAlpha(value, alpha) {
    const rgb = parseColor(value);
    if (!rgb) return null;
    return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})`;
  }

  // Берёт первый непустой ключ из themeParams.
  function pick(params, names) {
    for (let i = 0; i < names.length; i++) {
      if (params && params[names[i]]) return params[names[i]];
    }
    return '';
  }

  // Применяем цвета темы Telegram к CSS-переменным.
  function applyTheme() {
    const params = tg.themeParams || {};
    const dark = tg.colorScheme === 'dark';

    root.classList.toggle('tg-dark', dark);
    root.classList.toggle('tg-light', !dark);

    const bg = pick(params, ['bg', 'bg_color', 'theme_bg_color']);
    const text = pick(params, ['text', 'text_color', 'theme_text_color']);
    const hint = pick(params, ['hint', 'hint_color']);
    const secondaryBg = pick(params, ['secondary_bg_color']);
    const button = pick(params, ['button_color', 'link', 'link_color']);

    function set(name, value) {
      if (value) root.style.setProperty(name, value);
    }

    set('--bg', bg);
    set('--bg2', pick(params, ['header_bg_color']) || secondaryBg);
    set('--text', text);
    set('--hint', hint);
    set('--btn', button);
    set('--btn_text', pick(params, ['button_text_color']));
    set('--card', pick(params, ['section_bg_color']) || secondaryBg);
    set('--field', secondaryBg || bg);
    set('--danger', pick(params, ['destructive_text_color']));

    // Производные переменные - оттенки от цветов темы.
    set('--text2', pick(params, ['subtitle_text_color', 'secondary_hint_color']) || hint);
    set('--chip_text', hint);
    set('--btn2', pick(params, ['secondary_button_color']) || secondaryBg);
    set('--btn2_text', pick(params, ['secondary_button_text_color']) || text);
    set('--line', withAlpha(text, dark ? 0.14 : 0.12));
    set('--chip', withAlpha(text, dark ? 0.08 : 0.06));
    set('--btn_faint', withAlpha(button, 0.25));
    set('--danger_soft', withAlpha(pick(params, ['destructive_text_color']), 0.14));
    set('--shadow', `0 1px 2px ${withAlpha(text, dark ? 0.3 : 0.1)}`);

    // Цвет системной панели - чтобы приложение сливалось с окном Telegram.
    try {
      if (tg.setBackgroundColor && bg) tg.setBackgroundColor(bg);
      if (tg.setHeaderColor && bg) tg.setHeaderColor(bg);
    } catch (error) { /* старые версии клиента - не критично */ }

    // Цвет панели браузера - как в старой версии приложения.
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta && bg) meta.setAttribute('content', bg);
  }

  applyTheme();
  if (tg.onEvent) tg.onEvent('themeChanged', applyTheme);

  // Main button
  // Обработчик главной кнопки храним отдельно: у объекта MainButton из
  // Telegram SDK нет ни data, ни dataset - это свойства DOM-элементов.
  let mainButtonHandler = null;
  const mainButton = tg.MainButton;
  mainButton.setText('Сохранить');
  mainButton.onClick(() => {
    if (mainButtonHandler && window[mainButtonHandler]) window[mainButtonHandler]();
    else tg.showAlert('Кнопка не настроена для текущего экрана');
  });

  // Back button (Telegram BackButton)
  tg.BackButton.onClick(() => {
    window.history.back();
  });

  // Notification for user actions
  function showFlash(msg) {
    const el = document.getElementById('flash');
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => el.style.display = 'none', 3000);
  }

  // Цвет из темы (для графиков Chart.js)
  function themeColor(name, fallback) {
    const value = getComputedStyle(root).getPropertyValue(name).trim();
    return value || fallback;
  }

  // ------------------------------------------------------------
  // Auth: initData от Telegram
  // ------------------------------------------------------------
  // Telegram передаёт подпись в объекте WebApp (tg.initData). В query-строке
  // initData бывает только при открытии ссылки с параметром - на всякий
  // случай берём и оттуда.
  function getInitData() {
    if (tg.initData) return tg.initData;
    const params = new URLSearchParams(window.location.search);
    const initData = params.get('initData');
    return initData ? decodeURIComponent(initData) : '';
  }

  const INIT_DATA = getInitData();
  let currentUser = null;

  // Любой запрос к API идёт с заголовком X-Telegram-Init-Data: по нему
  // сервер проверяет подпись Telegram и пускает в приложение.
  function apiFetch(url, options = {}) {
    const opts = Object.assign({}, options);
    const headers = Object.assign({}, opts.headers || {});
    if (INIT_DATA) headers['X-Telegram-Init-Data'] = INIT_DATA;
    opts.headers = headers;
    startWait();
    return fetch(url, opts).finally(stopWait);
  }

  // Полоска загрузки сверху: пока идёт запрос - видно, что приложение ждёт.
  let pendingRequests = 0;
  function startWait() {
    pendingRequests += 1;
    const bar = document.getElementById('loadbar');
    if (bar) bar.classList.add('on');
  }
  function stopWait() {
    pendingRequests = Math.max(0, pendingRequests - 1);
    if (!pendingRequests) {
      const bar = document.getElementById('loadbar');
      if (bar) bar.classList.remove('on');
    }
  }

  async function initAuth() {
    if (!INIT_DATA) {
      setUserBadge('Нужен Telegram');
      showAuthMessage('Откройте приложение через Telegram-бота: вне Telegram данные недоступны.');
      return false;
    }
    try {
      const response = await apiFetch('/api/auth/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ initData: INIT_DATA })
      });
      const data = await response.json();
      if (data.ok) {
        currentUser = data.user;
        setUserBadge(`${currentUser.username} (${currentUser.role})`);
        return true;
      }
      setUserBadge('Нет доступа');
      showAuthMessage('Доступ к приложению не разрешён. Напишите боту - он выдаст доступ.');
      return false;
    } catch (err) {
      setUserBadge('Ошибка входа');
      showAuthMessage('Не удалось связаться с сервером. Проверьте соединение и обновите приложение.');
      return false;
    }
  }

  function showAuthMessage(text) {
    const main = document.getElementById('app-main');
    if (!main) return;
    main.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔒</div>
        <div>${text}</div>
      </div>
    `;
    const nav = document.getElementById('bottom-nav');
    if (nav) nav.classList.add('hidden');
  }

  function setUserBadge(text) {
    const badge = document.getElementById('user-badge');
    if (badge) badge.textContent = text;
  }

  // ------------------------------------------------------------
  // Экраны (вкладки)
  // ------------------------------------------------------------
  const TABS = ['dashboard', 'vehicles', 'expenses', 'barrels', 'reports'];
  let activeTab = 'dashboard';

  // Создаём блок каждой вкладки один раз и переключаем их видимость.
  function ensureViews() {
    const main = document.getElementById('app-main');
    if (!main) return;
    const skeleton = document.getElementById('skeleton');
    if (skeleton) skeleton.remove();
    TABS.forEach(name => {
      if (document.getElementById('view-' + name)) return;
      const view = document.createElement('section');
      view.id = 'view-' + name;
      view.className = 'app-view hidden';
      main.appendChild(view);
    });
  }

  function getView(name) {
    let view = document.getElementById('view-' + name);
    if (!view) {
      ensureViews();
      view = document.getElementById('view-' + name);
    }
    if (!view) return null;
    view.innerHTML = '';
    return view;
  }

  // Графики Chart.js: при скрытии экрана canvas схлопывается, поэтому
  // после возврата на вкладку графику нужно сказать "пересчитай размер".
  const charts = [];
  function resizeCharts() {
    charts.forEach(chart => {
      try { chart.resize(); } catch (e) { /* график мог быть удалён */ }
    });
  }

  function showTab(name) {
    if (!TABS.includes(name)) name = 'dashboard';
    activeTab = name;

    ensureViews();
    TABS.forEach(tab => {
      const view = document.getElementById('view-' + tab);
      if (view) view.classList.toggle('hidden', tab !== name);
    });

    // Нижняя навигация
    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.toggle('active', item.dataset.tab === name);
    });

    // Главная кнопка Telegram под текущий экран
    const mainBtn = tg.MainButton;
    if (name === 'vehicles') {
      mainBtn.setText('Добавить фуру');
      mainButtonHandler = 'saveVehicle';
      mainBtn.show();
    } else if (name === 'expenses') {
      mainBtn.setText('Добавить расход');
      mainButtonHandler = 'saveExpense';
      mainBtn.show();
    } else if (name === 'barrels') {
      mainBtn.setText('Обновить');
      mainButtonHandler = 'refreshBarrels';
      mainBtn.show();
    } else if (name === 'reports') {
      mainBtn.setText('Сформировать отчёт');
      mainButtonHandler = 'generateReport';
      mainBtn.show();
    } else {
      mainButtonHandler = null;
      mainBtn.hide();
    }

    loadTab(name);
    resizeCharts();
  }

  // Данные для вкладки грузим при первом открытии и по кнопке обновить.
  const loaded = {};
  function loadTab(name, force = false) {
    if (loaded[name] && !force) return;
    loaded[name] = true;
    switch (name) {
      case 'dashboard': loadDashboard(); break;
      case 'vehicles': loadVehicles(); break;
      case 'expenses': loadVehicles().then(loadExpenses); break;
      case 'barrels': loadBarrels(); break;
      case 'reports': loadReports(); break;
    }
  }

  // Initialize navigation
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', event => {
      event.preventDefault();
      showTab(item.dataset.tab);
    });
  });

  // ------------------------------------------------------------
  // Dashboard tab
  // ------------------------------------------------------------
  async function loadDashboard() {
    try {
      const r = await apiFetch('/api/dashboard?period=month');
      const data = await r.json();
      renderDashboard(data);
    } catch (err) {
      const view = getView('dashboard');
      if (view) view.innerHTML = '<div class="empty-state">Не удалось загрузить дашборд</div>';
    }
  }

  // Название периода по-русски (сервер отдаёт week/month/year/all).
  const PERIOD_NAMES = {
    week: 'за неделю', month: 'за месяц', year: 'за год', all: 'за всё время'
  };

  function renderDashboard(data) {
    const main = getView('dashboard');
    if (!main) return;

    const cardTotal = document.createElement('div');
    cardTotal.className = 'card';
    cardTotal.innerHTML = `
      <div class="card-title">Итоговые затраты ${PERIOD_NAMES[data.period] || data.period}</div>
      <div style="font-size: var(--font-size-2xl); font-weight: 700; margin-top: var(--spacing-sm);">
        ₴ ${Number(data.total_amount).toLocaleString()}
      </div>
    `;
    main.appendChild(cardTotal);

    // Top vehicles chart
    if (data.top_vehicles && data.top_vehicles.length > 0) {
      const cardVeh = document.createElement('div');
      cardVeh.className = 'card';
      cardVeh.innerHTML = `
        <div class="card-title">Топ-5 фур по затратам</div>
        <div class="chart-wrap"><canvas id="topVehiclesChart"></canvas></div>
      `;
      main.appendChild(cardVeh);
      renderTopVehiclesChart(data.top_vehicles);
    }

    // Expenses by category
    if (data.by_category && data.by_category.length > 0) {
      const cardCat = document.createElement('div');
      cardCat.className = 'card';
      cardCat.innerHTML = `
        <div class="card-title">Структура по категориям</div>
        <div class="chart-wrap"><canvas id="categoryChart"></canvas></div>
      `;
      main.appendChild(cardCat);
      renderCategoryChart(data.by_category);
    }

    // Barrels
    if (data.barrels && data.barrels.length > 0) {
      const cardBar = document.createElement('div');
      cardBar.className = 'card';
      cardBar.innerHTML = `
        <div class="card-title">Топливные бочки</div>
        <div style="margin-top: var(--spacing-sm);">
          ${data.barrels.map(b => `
            <div class="barrel-stats">
              <span>${b.name} (${b.fuel_type})</span>
              <span>${Number(b.current).toLocaleString()} л</span>
            </div>
          `).join('')}
        </div>
      `;
      main.appendChild(cardBar);
    }
  }

  function renderTopVehiclesChart(data) {
    const canvas = document.getElementById('topVehiclesChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.map(v => `${v.brand} ${v.plate}`).slice(0, 5),
        datasets: [{
          label: 'Затраты (₴)',
          data: data.map(v => v.total),
          backgroundColor: themeColor('--btn', '#3ba3ec')
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { color: themeColor('--hint', '#8a8a8a') } },
          x: { grid: { display: false }, ticks: { color: themeColor('--hint', '#8a8a8a') } }
        }
      }
    });
    charts.push(chart);
  }

  function renderCategoryChart(data) {
    const canvas = document.getElementById('categoryChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const labels = data.map(d => d.category);
    const totals = data.map(d => d.total);
    const bgColors = {
      "топливо": "#ff9500", "ремонт": "#3ba3ec", "запчасти": "#bf5af2",
      "шины": "#8e8e93", "штрафы": "#e53935", "дорога": "#5ac8fa",
      "дорога/платные участки": "#5ac8fa", "мойка": "#4caf50", "прочее": "#8e8e93"
    };
    // Цвет даём по названию категории, а не по позиции - иначе цвета
    // путаются при изменении порядка.
    const colors = labels.map(cat => bgColors[cat] || "#8e8e93");
    const chart = new Chart(ctx, {
      type: 'pie',
      data: { labels, datasets: [{ data: totals, backgroundColor: colors }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { color: themeColor('--text2', '#b8b8b8') } } }
      }
    });
    charts.push(chart);
  }

  // ------------------------------------------------------------
  // Vehicles tab
  // ------------------------------------------------------------
  let vehicles = [];

  async function loadVehicles() {
    const r = await apiFetch('/api/vehicles');
    vehicles = await r.json();
    if (activeTab === 'vehicles') renderVehiclesList();
    return vehicles;
  }

  function renderVehiclesList(filter = '') {
    const main = getView('vehicles');
    if (!main) return;

    const header = document.createElement('div');
    header.innerHTML = `
      <div class="card-title">Фуры ${filter ? `(отфильтровано: ${filter})` : ''}</div>
      <button class="btn btn-primary" id="add-vehicle-btn">Добавить фуру</button>
    `;
    main.appendChild(header);

    const list = document.createElement('div');
    list.style.marginTop = 'var(--spacing-md)';

    if (vehicles.length === 0) {
      list.innerHTML = `<div class="empty-state">
        <div class="empty-icon">🚚</div>
        <div>Фуры отсутствуют</div>
        <div>Нажмите "Добавить фуру" для создания первой</div>
      </div>`;
    } else {
      vehicles.forEach(v => {
        const card = document.createElement('div');
        card.className = 'vehicle-card';
        card.innerHTML = `
          <div class="vehicle-icon">${(v.brand || '?').charAt(0)}</div>
          <div class="vehicle-info">
            <div class="vehicle-name">${v.brand} ${v.plate}</div>
            <div class="vehicle-plate">Гос. номер: ${v.plate}</div>
          </div>
          <div class="vehicle-status">
            <span class="vehicle-status-value">${v.current_mileage} км</span>
            <span>Норм расхода: ${v.avg_fuel_consumption} л/100км</span>
          </div>
        `;
        list.appendChild(card);
      });
    }
    main.appendChild(list);

    const addBtn = document.getElementById('add-vehicle-btn');
    if (addBtn) addBtn.addEventListener('click', openVehicleForm);
  }

  // Форма добавления фуры
  function openVehicleForm() {
    const main = getView('vehicles');
    if (!main) return;

    main.innerHTML = `
      <div class="card">
        <div class="card-title">Новая фура</div>
        <form id="vehicle-form">
          <div class="field">
            <label class="field-label" for="vehicle_plate">Гос. номер</label>
            <input id="vehicle_plate" class="field-input" type="text" name="plate" required>
          </div>
          <div class="field">
            <label class="field-label" for="vehicle_brand">Марка</label>
            <input id="vehicle_brand" class="field-input" type="text" name="brand" required>
          </div>
          <div class="field">
            <label class="field-label" for="vehicle_mileage">Пробег, км</label>
            <input id="vehicle_mileage" class="field-input" type="number" name="current_mileage" min="0" step="1" value="0">
          </div>
          <div class="field">
            <label class="field-label" for="vehicle_consumption">Расход, л/100км</label>
            <input id="vehicle_consumption" class="field-input" type="number" name="avg_fuel_consumption" min="0" step="0.1" value="30">
          </div>
          <div style="margin-top: var(--spacing-md); display: flex; justify-content: flex-end; gap: var(--spacing-sm);">
            <button type="button" class="btn btn-secondary" onclick="renderVehiclesList()">Отмена</button>
            <button type="submit" class="btn btn-primary">Сохранить</button>
          </div>
        </form>
      </div>
    `;

    const form = document.getElementById('vehicle-form');
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(form).entries());
      data.current_mileage = Number(data.current_mileage) || 0;
      data.avg_fuel_consumption = Number(data.avg_fuel_consumption) || 0;
      data.driver_id = currentUser ? currentUser.id : null;
      try {
        const r = await apiFetch('/api/vehicles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        const answer = await r.json();
        if (!r.ok) {
          tg.showAlert(answer.error === 'plate exists' ? 'Такая фура уже есть в списке' : 'Не удалось сохранить фуру');
          return;
        }
        showFlash('Фура добавлена');
        await loadVehicles();
        renderVehiclesList();
      } catch (err) {
        tg.showAlert('Ошибка при добавлении фуры');
      }
    });
  }

  // Кнопка Telegram на экране "Фуры"
  function saveVehicle() {
    const form = document.getElementById('vehicle-form');
    if (form) form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit'));
    else openVehicleForm();
  }

  // ------------------------------------------------------------
  // Expenses tab
  // ------------------------------------------------------------
  let expenses = [];

  async function loadExpenses() {
    const r = await apiFetch('/api/expenses');
    expenses = await r.json();
    if (activeTab === 'expenses') renderExpensesList();
  }

  function renderExpensesList() {
    const main = getView('expenses');
    if (!main) return;

    const header = document.createElement('div');
    header.className = 'card';
    header.innerHTML = `
      <div class="card-title">Расходы</div>
      <div class="filter-row">
        <select id="filter-vehicle" class="field-select">
          <option value="">Все фуры</option>
          ${vehicles.map(v => `<option value="${v.id}">${v.display_name || v.plate}</option>`).join('')}
        </select>
        <input id="filter-category" class="field-input" placeholder="Категория...">
        <input id="filter-datefrom" class="field-input" type="date" placeholder="Дата от">
        <input id="filter-dateto" class="field-input" type="date" placeholder="Дата до">
        <div class="filter-actions">
          <button class="btn btn-secondary" onclick="applyExpenseFilters()">Применить</button>
          <button class="btn btn-secondary" onclick="clearExpenseFilters()">Сбросить</button>
        </div>
      </div>
    `;
    main.appendChild(header);

    const list = document.createElement('div');
    list.style.marginTop = 'var(--spacing-md)';

    if (expenses.length === 0) {
      list.innerHTML = `<div class="empty-state">
        <div class="empty-icon">💸</div>
        <div>Расходов нет</div>
        <div>Добавьте первый расход кнопкой ниже</div>
      </div>`;
    } else {
      expenses.forEach(e => {
        const card = document.createElement('div');
        card.className = 'expense-row';
        card.innerHTML = `
          <div class="expense-left">
            <div class="expense-category badge badge-${getCategoryClass(e.category)}">${e.category}</div>
            <div class="expense-info">
              <div class="expense-comment">${e.comment || '-'}</div>
              <div class="expense-meta">${e.date ? new Date(e.date).toLocaleDateString('ru-RU') : '-'}</div>
            </div>
          </div>
          <div class="expense-right">
            <div class="expense-amount">${Number(e.amount).toLocaleString()} ₴</div>
            <div class="expense-date">${new Date(e.date).toLocaleDateString('ru-RU')}</div>
          </div>
        `;
        list.appendChild(card);
      });
    }
    main.appendChild(list);

    const addBtn = document.createElement('button');
    addBtn.className = 'btn btn-primary w-full mb-2';
    addBtn.textContent = 'Добавить расход';
    addBtn.onclick = () => openExpenseForm();
    main.appendChild(addBtn);
  }

  function getCategoryClass(cat) {
    const map = { "топливо": "primary", "ремонт": "primary", "запчасти": "info", "шины": "warning", "штрафы": "danger", "дорога": "info", "мойка": "success", "прочее": "gray" };
    return map[cat] || "gray";
  }

  async function applyExpenseFilters() {
    const veh = document.getElementById('filter-vehicle').value;
    const cat = document.getElementById('filter-category').value.toLowerCase();
    const from = document.getElementById('filter-datefrom').value;
    const to = document.getElementById('filter-dateto').value;
    // Собираем запрос с фильтрами и перерисовываем список на месте.
    const params = new URLSearchParams();
    if (veh) params.set('vehicle_id', veh);
    if (cat) params.set('category', cat);
    if (from) params.set('date_from', from);
    if (to) params.set('date_to', to);
    const r = await apiFetch(`/api/expenses?${params.toString()}`);
    expenses = await r.json();
    renderExpensesList();
  }

  function clearExpenseFilters() {
    document.getElementById('filter-vehicle').value = '';
    document.getElementById('filter-category').value = '';
    document.getElementById('filter-datefrom').value = '';
    document.getElementById('filter-dateto').value = '';
    loadExpenses();
  }

  function openExpenseForm(expense = null) {
    const main = getView('expenses');
    if (!main) return;

    const vehicle = vehicles.find(v => v.id === (expense?.vehicle_id || null));

    main.innerHTML = `
      <div class="card">
        <div class="card-title">${expense ? 'Редактировать расход' : 'Добавить расход'}</div>
        <form id="expense-form">
          <input type="hidden" name="expense_id" value="${expense?.id || ''}">
          <div class="field">
            <label class="field-label" for="vehicle_select">Фура</label>
            <select id="vehicle_select" class="field-select" name="vehicle_id" required>
              <option value="">— выберите фуру —</option>
              ${vehicles.map(v => `<option value="${v.id}" ${(expense?.vehicle_id === v.id) ? 'selected' : ''}>${v.display_name || v.plate}</option>`).join('')}
            </select>
          </div>
          <div class="field">
            <label class="field-label" for="category">Категория</label>
            <select id="category" class="field-select" name="category">
              <option value="топливо" ${(expense?.category === 'топливо') ? 'selected' : ''}>топливо</option>
              <option value="ремонт" ${(expense?.category === 'ремонт') ? 'selected' : ''}>ремонт</option>
              <option value="запчасти" ${(expense?.category === 'запчасти') ? 'selected' : ''}>запчасти</option>
              <option value="шины" ${(expense?.category === 'шины') ? 'selected' : ''}>шины</option>
              <option value="штрафы" ${(expense?.category === 'штрафы') ? 'selected' : ''}>штрафы</option>
              <option value="дорога/платные участки" ${(expense?.category === 'дорога/платные участки') ? 'selected' : ''}>дорога/платные участки</option>
              <option value="мойка" ${(expense?.category === 'мойка') ? 'selected' : ''}>мойка</option>
              <option value="прочее" ${(expense?.category === 'прочее') ? 'selected' : ''}>прочее</option>
            </select>
          </div>
          <div class="field">
            <label class="field-label" for="amount">Сумма (₴)</label>
            <input id="amount" class="field-input" type="number" name="amount" min="0" step="100" value="${expense?.amount || ''}" required>
          </div>
          <div class="field">
            <label class="field-label" for="date">Дата</label>
            <input id="date" class="field-input" type="date" name="date" value="${expense ? new Date(expense.date).toISOString().split('T')[0] : ''}" required>
          </div>
          <div class="field">
            <label class="field-label" for="comment">Комментарий</label>
            <textarea id="comment" class="field-input" name="comment">${expense?.comment || ''}</textarea>
          </div>
          <div class="field">
            <label class="field-label" for="photo_url">Фото чека (URL)</label>
            <input id="photo_url" class="field-input" type="text" name="photo_url" value="${expense?.photo_url || ''}">
            <small>Ссылка на загруженное фото (или оставьте пустым)</small>
          </div>
          <div style="margin-top: var(--spacing-md); display: flex; justify-content: flex-end; gap: var(--spacing-sm);">
            <button type="button" class="btn btn-secondary" onclick="renderExpensesList()">Отмена</button>
            <button type="submit" class="btn btn-primary">Сохранить</button>
          </div>
        </form>
      </div>
    `;

    document.getElementById('expense-form').addEventListener('submit', async e => {
      e.preventDefault();
      const form = e.target;
      const data = Object.fromEntries(new FormData(form).entries());
      // Сервер ждёт число, а не строку из формы.
      data.amount = Number(data.amount);
      data.vehicle_id = Number(data.vehicle_id);
      const method = data.expense_id ? 'PUT' : 'POST';
      const url = data.expense_id ? `/api/expenses/${data.expense_id}` : '/api/expenses';
      try {
        const r = await apiFetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        const answer = await r.json();
        if (!r.ok) {
          tg.showAlert(answer.error || 'Не удалось сохранить расход');
          return;
        }
        showFlash('Сохранено');
        await loadExpenses();
        renderExpensesList();
      } catch (err) {
        tg.showAlert('Ошибка сохранения');
      }
    });
  }

  // Кнопка Telegram на экране "Расходы"
  function saveExpense() {
    const form = document.getElementById('expense-form');
    if (form) form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit'));
    else openExpenseForm();
  }

  // ------------------------------------------------------------
  // Barrels tab
  // ------------------------------------------------------------
  async function loadBarrels() {
    const main = getView('barrels');
    if (!main) return;

    main.innerHTML = '<div class="skeleton-wrap"><div class="skeleton-line w-full"></div><div class="skeleton-line w-80"></div></div>';

    try {
      const r = await apiFetch('/api/dashboard?period=all');
      const data = await r.json();
      const barrels = data.barrels || [];

      main.innerHTML = '';
      const header = document.createElement('div');
      header.className = 'card';
      header.innerHTML = `
        <div class="card-title">Топливные бочки</div>
        <button class="btn btn-secondary" onclick="refreshBarrels()">Обновить</button>
      `;
      main.appendChild(header);

      const mainContent = document.createElement('div');
      mainContent.style.marginTop = 'var(--spacing-md)';

      if (barrels.length === 0) {
        mainContent.innerHTML = `<div class="empty-state">
          <div class="empty-icon">⛽</div>
          <div>Бочки не настроены</div>
          <div>Ёмкости добавляются через бэкенд API</div>
        </div>`;
      } else {
        barrels.forEach(b => {
          const lowCls = b.is_low ? 'low' : '';
          const card = document.createElement('div');
          card.className = 'barrel-card';
          card.innerHTML = `
            <div class="barrel-header">
              <span class="barrel-type ${b.fuel_type}">${b.name} (${b.fuel_type})</span>
              <span class="barrel-stats">
                <span class="barrel-stats-value">${Number(b.current).toLocaleString()} л</span>
                <span>${Number(b.capacity).toLocaleString()} л</span>
              </span>
            </div>
            <div class="barrel-level-wrap">
              <div class="barrel-level-fill ${lowCls}" style="width: ${b.remaining_pct}%;">
                ${b.remaining_pct}%
              </div>
            </div>
            <div class="barrel-stats">
              <span>порог уведомления: ${b.threshold_liters} л</span>
              <span>уровень: ${b.formatted_remaining}</span>
            </div>
          `;
          mainContent.appendChild(card);
        });
      }
      main.appendChild(mainContent);
    } catch (err) {
      main.innerHTML = '<div class="empty-state">Не удалось загрузить бочки</div>';
    }
  }

  function refreshBarrels() { loadBarrels(); }

  // ------------------------------------------------------------
  // Reports tab
  // ------------------------------------------------------------
  function loadReports() {
    const main = getView('reports');
    if (!main) return;

    main.innerHTML = `
      <div class="card">
        <div class="card-title">Отчеты и экспорт</div>
        <div style="margin-top: var(--spacing-sm);">
          <label class="field-label" for="report-period">Период</label>
          <select id="report-period" class="field-select">
            <option value="week">Неделя</option>
            <option value="month" selected>Месяц</option>
            <option value="year">Год</option>
            <option value="all">Весь период</option>
          </select>
          <button class="btn btn-primary mt-sm" onclick="generateReport()">Сформировать отчёт</button>
        </div>
      </div>
      <div style="margin-top: var(--spacing-md);">
        <p>Нажмите кнопку выше для формирования отчёта.</p>
        <p>Экспорт в CSV/PDF будет добавлен в следующих версиях.</p>
      </div>
    `;
  }

  function generateReport() {
    const select = document.getElementById('report-period');
    const period = select ? select.value : 'month';
    apiFetch(`/api/dashboard?period=${period}`)
      .then(r => r.json())
      .then(data => {
        const lines = [`Car Tracker — Отчёт ${PERIOD_NAMES[period] || period}`, '===', '',
          `Итоговая сумма: ₴ ${Number(data.total_amount).toLocaleString()}`,
          '',
          'Топ-5 фур по затратам:'];
        (data.top_vehicles || []).slice(0, 5).forEach(v => {
          lines.push(`  - ${v.brand} ${v.plate}: ₴ ${v.total.toLocaleString()}`);
        });
        lines.push('', 'Структура по категориям:');
        (data.by_category || []).forEach(c => {
          lines.push(`  - ${c.category}: ₴ ${c.total.toLocaleString()}`);
        });
        tg.showAlert(lines.join('\n'));
      });
  }

  // ------------------------------------------------------------
  // Экспорт в window: разметка вызывает эти функции через onclick=
  // ------------------------------------------------------------
  window.renderVehiclesList = renderVehiclesList;
  window.renderExpensesList = renderExpensesList;
  window.applyExpenseFilters = applyExpenseFilters;
  window.clearExpenseFilters = clearExpenseFilters;
  window.openExpenseForm = openExpenseForm;
  window.openVehicleForm = openVehicleForm;
  window.refreshBarrels = refreshBarrels;
  window.generateReport = generateReport;
  window.saveVehicle = saveVehicle;
  window.saveExpense = saveExpense;
  window.showTab = showTab;

  // ------------------------------------------------------------
  // Initialization
  // ------------------------------------------------------------
  initAuth().then(ok => {
    // Без авторизации данные недоступны - показывать их незачем.
    if (!ok) return;
    ensureViews();
    showTab('dashboard');
  });
})();

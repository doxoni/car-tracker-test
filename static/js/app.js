// -*- coding: utf-8 -*-
/* Car Tracker — Telegram Mini App SPA
   Features: auth via initData, fleet list, expenses, dashboard + charts,
              fuel barrels (read), analytics, Telegram theme support.
*/

(() => {
  "use strict";

  // ------------------------------------------------------------
  // Telegram Web App init
  // ------------------------------------------------------------
  const tg = window.Telegram.WebApp;
  tg.expand();
  tg.setHeaderColor('#1c1c1e');

  const root = document.documentElement;
  // Telegram theme CSS variables
  root.style.setProperty('--tg-theme-bg-color', getComputedStyle(document.body).backgroundColor || '#ffffff');
  root.style.setProperty('--tg-theme-text-color', getComputedStyle(document.body).color || '#1c1c1e');

  // Main button
  const mainBtnWrap = document.getElementById('main-button-wrap');
  const mainButton = tg.MainButton;
  mainButton.setText('Сохранить');
  mainButton.onClick(() => {
    // context-dependent — filled per-tab
    const handler = mainBtn.dataset.onclick;
    if (handler && window[handler]) window[handler]();
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

  // ------------------------------------------------------------
  // Auth: receive initData from Telegram via query string or postMessage
  // ------------------------------------------------------------
  function getInitData() {
    // Приложение запускается через Mini App — initData приходит в query string
    const params = new URLSearchParams(window.location.search);
    const initData = params.get('initData');
    if (initData) return decodeURIComponent(initData);
    // Иначе можно слушать postMessage от бота — но для MVP используем query
    return null;
  }

  // Отправка initData бэкенду (демо-режим, пока сервер не поднят)
  let currentUser = null;

  function initAuth() {
    const initData = getInitData();
    if (!initData) {
      // Без initData работаем в демо-режиме с фиктивным юзером
      currentUser = { tg_id: 0, role: 'admin', username: 'demo' };
      setUserBadge('Демо-режим');
      return;
    }
    // Отправляем на бэкенд для верификации HMAC
    fetch(`/api/auth/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData })
    })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        currentUser = data.user;
        setUserBadge(`${currentUser.username} (${currentUser.role})`);
      } else {
        tg.showAlert('Авторизация не прошла. Попробуйте снова.');
      }
    })
    .catch(() => {
      // Fallback: демо-режим, если бекенд недоступен
      currentUser = { tg_id: 0, role: 'admin', username: 'demo' };
      setUserBadge('Дemo-режим (fallback)');
    });
  }

  function setUserBadge(text) {
    const badge = document.getElementById('user-badge');
    if (badge) badge.textContent = text;
  }

  // ------------------------------------------------------------
  // State management — вкладки
  // ------------------------------------------------------------
  const tabs = {
    dashboard: '#dashboard',
    vehicles: '#vehicles',
    expenses: '#expenses',
    barrels: '#barrels',
    reports: '#reports'
  };

  function showTab(name) {
    // Обновляем нижнюю навигацию
    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.toggle('active', item.dataset.tab === name);
    });

    // Скрываем все контейнеры
    Object.values(tabs).forEach(id => {
      const el = document.querySelector(id);
      if (el) el.classList.add('hidden');
    });

    // Показываем выбранную вкладку
    const target = document.querySelector(tabs[name]);
    if (target) target.classList.remove('hidden');

    // Настраиваем MainButton под вкладку
    const mainBtn = tg.MainButton;
    if (name === 'vehicles') {
      mainBtn.setText('Сохранить фуру');
      mainBtn.data.onclick = 'saveVehicle';
      mainBtn.show();
    } else if (name === 'expenses') {
      mainBtn.setText('Добавить расход');
      mainBtn.data.onclick = 'saveExpense';
      mainBtn.show();
    } else if (name === 'barrels') {
      mainBtn.setText('Обновить');
      mainBtn.data.onclick = 'refreshBarrels';
      mainBtn.show();
    } else if (name === 'reports') {
      mainBtn.setText('Сформировать отчёт');
      mainBtn.data.onclick = 'generateReport';
      mainBtn.show();
    } else {
      mainBtn.hide();
    }
  }

  // Initialize navigation
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      const tab = item.dataset.tab;
      showTab(tab);
    });
  });

  // Show dashboard by default
  showTab('dashboard');

  // ------------------------------------------------------------
  // Dashboard tab
  // ------------------------------------------------------------
  function renderDashboard(data) {
    const main = document.getElementById('app-main');
    main.innerHTML = '';

    const cardTotal = document.createElement('div');
    cardTotal.className = 'card';
    cardTotal.innerHTML = `
      <div class="card-title">Итоговые затраты ${data.period}</div>
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
        <canvas id="topVehiclesChart" class="chart-wrap"></canvas>
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
        <canvas id="categoryChart" class="chart-wrap"></canvas>
      `;
      main.appendChild(cardCat);
      renderCategoryChart(data.by_category);
    }

    // Barrels (only admin)
    if (data.barrels && data.barrels.length > 0) {
      const cardBar = document.createElement('div');
      cardBar.className = 'card';
      cardBar.innerHTML = `
        <div class="card-title">Топливо в бочках</div>
        <div style="margin-top: var(--spacing-md);">
      `;
      data.barrels.forEach(b => {
        const lowCls = b.is_low ? 'low' : '';
        cardBar.innerHTML += `
          <div class="barrel-card">
            <div class="barrel-header">
              <span class="barrel-type ${b.fuel_type}">${b.name} (${b.fuel_type})</span>
              <span class="barrel-stats">
                <span class="barrel-stats-value">${Number(b.current).toLocaleString()} л</span>
                <span>${Number(b.capacity).toLocaleString()} л максимум</span>
              </span>
            </div>
            <div class="barrel-level-wrap">
              <div class="barrel-level-fill ${lowCls}" style="width: ${b.remaining_pct}%; --level-color: #5ac8fa; --level-color-light: #b2d7ff;">
                ${b.remaining_pct}%
              </div>
            </div>
            <div class="barrel-stats">
              <span>остаток: ${b.formatted_remaining}</span>
            </div>
          </div>
        `;
      });
      cardBar.innerHTML += `</div>`;
      main.appendChild(cardBar);
    }
  }

  function renderTopVehiclesChart(data) {
    const ctx = document.getElementById('topVehiclesChart').getContext('2d');
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.map(v => `${v.brand} ${v.plate}`).slice(0, 5),
        datasets: [{ label: 'Затраты (₽)', data: data.map(v => v.total), backgroundColor: '#007aff' }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { y: { beginAtZero: true, ticks: { stepSize: 5000 } }, x: { grid: { display: false } } }
      }
    });
  }

  function renderCategoryChart(data) {
    const ctx = document.getElementById('categoryChart').getContext('2d');
    const labels = data.map(d => d.category);
    const totals = data.map(d => d.total);
    const bgColors = {
      "топливо": "#ff9500", "ремонт": "#007aff", "запчасти": "#bf5af2",
      "шины": "#8e8e93", "штрафы": "#ff3b30", "дорога": "#5ac8fa", "мойка": "#34c759", "прочее": "#8e8e93"
    };
    new Chart(ctx, {
      type: 'pie',
      data: { labels, datasets: [{ data: totals, backgroundColor: Object.values(bgColors) }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
    });
  }

  // ------------------------------------------------------------
  // Vehicles tab
  // ------------------------------------------------------------
  let vehicles = [];

  async function loadVehicles() {
    const r = await fetch('/api/vehicles');
    vehicles = await r.json();
    renderVehiclesList();
  }

  function renderVehiclesList(filter = '') {
    const main = document.getElementById('app-main');
    main.innerHTML = '';

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
          <div class="vehicle-icon">${v.brand.charAt(0)}</div>
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

    // Add vehicle handler (admin only in demo)
    document.getElementById('add-vehicle-btn').addEventListener('click', () => {
      if (!currentUser || !currentUser.is_admin) return tg.showAlert('Только админ');
      const plate = prompt('Гос. номер фуры:');
      if (!plate) return;
      const brand = prompt('Марка фуры:');
      if (!brand) return;
      fetch('/api/vehicles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plate: plate.toUpperCase(), brand, driver_id: currentUser.tg_id || 1, wialon_id: null, current_mileage: 0, avg_fuel_consumption: 30 })
      })
      .then(r => r.json())
      .then(() => showFlash('Фура добавлена') || loadVehicles())
      .catch(() => tg.showAlert('Ошибка при добавлении'));
    });
  }

  // ------------------------------------------------------------
  // Expenses tab
  // ------------------------------------------------------------
  let expenses = [];

  async function loadExpenses() {
    const r = await fetch('/api/expenses?period=month');
    expenses = await r.json();
    renderExpensesList();
  }

  function renderExpensesList() {
    const main = document.getElementById('app-main');
    main.innerHTML = '';

    const header = document.createElement('div');
    header.className = 'card';
    header.innerHTML = `
      <div class="card-title">Расходы</div>
      <div style="margin-top: var(--spacing-sm); display: flex; gap: var(--spacing-sm); flex-wrap: wrap;">
        <select id="filter-vehicle" class="field-select">
          <option value="">Все фуры</option>
          ${vehicles.map(v => `<option value="${v.id}">${v.display_name}</option>`).join('')}
        </select>
        <input id="filter-category" class="field-input" placeholder="Категория...">
        <input id="filter-datefrom" class="field-input" type="date" placeholder="Дата от">
        <input id="filter-dateto" class="field-input" type="date" placeholder="Дата до">
        <button class="btn btn-secondary" onclick="applyExpenseFilters()">Применить</button>
        <button class="btn btn-primary" onclick="clearExpenseFilters()">Сбросить</button>
      </div>
    `;
    main.appendChild(header);

    const list = document.createElement('div');
    list.style.marginTop = 'var(--spacing-md)';

    if (expenses.length === 0) {
      list.innerHTML = `<div class="empty-state">
        <div class="empty-icon">💸</div>
        <div>Расходов нет</div>
        <div>Добавьте первый расход через вкладку "Фуры"</div>
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

    // Add expense button
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

  function applyExpenseFilters() {
    const veh = document.getElementById('filter-vehicle').value;
    const cat = document.getElementById('filter-category').value.toLowerCase();
    const from = document.getElementById('filter-datefrom').value;
    const to = document.getElementById('filter-dateto').value;
    // reload from server with params
    window.location = `/api/expenses?vehicle_id=${veh}&category=${cat}&date_from=${from}&date_to=${to}`;
  }

  function clearExpenseFilters() {
    document.getElementById('filter-vehicle').value = '';
    document.getElementById('filter-category').value = '';
    document.getElementById('filter-datefrom').value = '';
    document.getElementById('filter-dateto').value = '';
    loadExpenses();
  }

  function openExpenseForm(expense = null) {
    const main = document.getElementById('app-main');
    main.innerHTML = '';

    const vehicle = vehicles.find(v => v.id === (expense?.vehicle_id || null));

    main.innerHTML = `
      <div class="card" style="max-width: 560px; margin: 0 auto;">
        <div class="card-title">${expense ? 'Редактировать расход' : 'Добавить расход'}</div>
        <form id="expense-form">
          <input type="hidden" name="expense_id" value="${expense?.id || ''}">
          <div class="field">
            <label class="field-label" for="vehicle_select">Фура</label>
            <select id="vehicle_select" class="field-select" disabled>
              <option value="">— выберите фуру —</option>
              ${vehicles.map(v => `<option value="${v.id}" ${(expense?.vehicle_id === v.id) ? 'selected' : ''}>${v.display_name}</option>`).join('')}
            </select>
          </div>
          <div class="field">
            <label class="field-label" for="category">Категория</label>
            <select id="category" class="field-select">
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
            <label class="field-label" for="amount">Сумма (₽)</label>
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

    document.getElementById('expense-form').addEventListener('submit', e => {
      e.preventDefault();
      const form = e.target;
      const data = Object.fromEntries(new FormData(form).entries());
      const method = data.expense_id ? 'PUT' : 'POST';
      const url = `/api/expenses/${data.expense_id || ''}`;
      fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
      .then(r => r.json())
      .then(() => showFlash('Сохранено') || loadExpenses())
      .catch(() => tg.showAlert('Ошибка сохранения'));
    });
  }

  // ------------------------------------------------------------
  // Barrels tab (read-only MVP)
  // ------------------------------------------------------------
  function renderBarrels() {
    const main = document.getElementById('app-main');
    main.innerHTML = '';

    const header = document.createElement('div');
    header.className = 'card';
    header.innerHTML = `
      <div class="card-title">Топливные бочки</div>
      <button class="btn btn-secondary" onclick="refreshBarrels()">Обновить</button>
    `;
    main.appendChild(header);

    fetch('/api/dashboard?period=all')
      .then(r => r.json())
      .then(data => {
        const barrels = data.barrels || [];
        const mainContent = document.createElement('div');
        mainContent.style.marginTop = 'var(--spacing-md)';

        if (barrels.length === 0) {
          mainContent.innerHTML = `<div class="empty-state">
            <div class="empty-icon">⛽</div>
            <div>Бочки не настроены</div>
            <div>Админ может добавить ёмкости через бэкенд API</div>
          </div>`;
        } else {
          barrels.forEach(b => {
            const lowCls = b.is_low ? 'low' : '';
            mainContent.innerHTML += `
              <div class="barrel-card">
                <div class="barrel-header">
                  <span class="barrel-type ${b.fuel_type}">${b.name} (${b.fuel_type})</span>
                  <span class="barrel-stats">
                    <span class="barrel-stats-value">${Number(b.current).toLocaleString()} л</span>
                    <span>${Number(b.capacity).toLocaleString()} л</span>
                  </span>
                </div>
                <div class="barrel-level-wrap">
                  <div class="barrel-level-fill ${lowCls}" style="width: ${b.remaining_pct}%; --level-color: #5ac8fa; --level-color-light: #b2d7ff;">
                    ${b.remaining_pct}%
                  </div>
                </div>
                <div class="barrel-stats">
                  <span>порог уведомления: ${b.threshold_liters} л</span>
                  <span>уровень: ${b.formatted_remaining}</span>
                </div>
              </div>
            `;
          });
        }
        main.appendChild(mainContent);
      })
      .catch(() => tg.showAlert('Ошибка загрузки бочек'));
  }

  function refreshBarrels() { renderBarrels(); }

  // ------------------------------------------------------------
  // Reports tab
  // ------------------------------------------------------------
  function renderReports() {
    const main = document.getElementById('app-main');
    main.innerHTML = '';

    const header = document.createElement('div');
    header.className = 'card';
    header.innerHTML = `
      <div class="card-title">Отчеты и экспорт</div>
      <div style="margin-top: var(--spacing-sm);">
        <label class="field-label">Период</label>
        <select id="report-period" class="field-select">
          <option value="week">Неделя</option>
          <option value="month" selected>Месяц</option>
          <option value="year">Год</option>
          <option value="all">Весь период</option>
        </select>
        <button class="btn btn-primary mt-sm" onclick="generateReport()">Сформировать отчёт</button>
      </div>
    `;
    main.appendChild(header);

    const mainContent = document.createElement('div');
    mainContent.style.marginTop = 'var(--spacing-md)';
    mainContent.innerHTML = `
      <p>Нажмите кнопку выше для формирования отчёта.</p>
      <p>Экспорт в CSV/PDF будет добавлен в следующих версиях.</p>
    `;
    main.appendChild(mainContent);
  }

  function generateReport() {
    const period = document.getElementById('report-period').value;
    fetch(`/api/dashboard?period=${period}`)
      .then(r => r.json())
      .then(data => {
        // Simple PDF-like view
        const lines = [`Car Tracker — Отчет за ${period}`, '===', '',
          `Итоговая сумма: ₴ ${Number(data.total_amount).toLocaleString()}`,
          '',
          'Топ-5 фур по затратам:'];
        data.top_vehicles.slice(0, 5).forEach(v => {
          lines.push(`  - ${v.brand} ${v.plate}: ₴ ${v.total.toLocaleString()}`);
        });
        lines.push('', 'Структура по категориям:');
        data.by_category.forEach(c => {
          lines.push(`  - ${c.category}: ₴ ${c.total.toLocaleString()}`);
        });
        tg.showAlert(lines.join('\n'));
      });
  }

  // ------------------------------------------------------------
  // Initialization
  // ------------------------------------------------------------
  initAuth().then(() => {
    // Load data for all tabs
    loadVehicles();
    loadExpenses();

    // Set up tab switching after data loads
    setTimeout(() => {
      // Dashboard first
      fetch('/api/dashboard?period=month')
        .then(r => r.json())
        .then(data => renderDashboard(data));
    }, 500);
  });
})();
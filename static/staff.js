/* Staff settings use the real, CSRF-protected registry API. */
(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const roles = {
    owner: 'Владелец', admin: 'Администратор', store_manager: 'Управляющий магазином',
    catalog_manager: 'Менеджер каталога', warehouse_operator: 'Оператор склада',
    order_manager: 'Менеджер заказов', marketing_manager: 'Маркетолог',
    content_editor: 'Редактор контента', courier: 'Курьер', customer_support: 'Поддержка',
    finance_analyst: 'Финансовый аналитик', partner: 'Партнёр'
  };
  const errors = {
    invalid_credentials: 'Неверные данные для входа.', permission_denied: 'У вашей роли нет права на это действие.',
    admin_auth_required: 'Сеанс завершён. Войдите снова.', username_exists: 'Этот логин уже занят.',
    invalid_username: 'Логин: 3–64 латинских символа, цифры, точка, дефис или подчёркивание.',
    password_length_12_to_256: 'Пароль должен содержать от 12 до 256 символов.',
    reauthentication_failed: 'Текущий пароль не подошёл.', reauthentication_throttled: 'Слишком много ошибок пароля. Повторите через 15 минут.',
    mfa_confirmation_throttled: 'Слишком много ошибок кода. Повторите через 15 минут.',
    invalid_mfa_code: 'Код не подошёл. Проверьте время устройства и введите новый код.',
    mfa_enrollment_expired: 'Время настройки истекло. Начните подключение MFA заново.',
    mfa_already_enabled: 'MFA уже подключена.', mfa_enrollment_changed: 'Настройка изменилась. Начните заново.',
    owner_required: 'Это действие доступно только владельцу.',
    use_personal_security_settings: 'Для своего пароля используйте раздел «Моя безопасность».',
    bootstrap_password_managed_in_environment: 'Пароль bootstrap-владельца меняется через настройки окружения.'
  };
  let context, secretTimer;
  const when = seconds => new Intl.DateTimeFormat('ru-RU', {dateStyle:'short', timeStyle:'short', timeZone:'Europe/Moscow'}).format(new Date(Number(seconds) * 1000));
  const message = error => errors[error.code] || error.message || 'Не удалось выполнить действие.';
  const roleOptions = (available, selected) => available.filter(role => context.principal.role === 'owner' || !['owner','admin'].includes(role))
    .map(role => `<option value="${esc(role)}" ${role === selected ? 'selected' : ''}>${esc(roles[role] || role)}</option>`).join('');

  function clearSecrets() {
    clearTimeout(secretTimer);
    const box = $('#mfaProvisioning');
    if (box) { box.hidden = true; $('#mfaSecret').textContent = ''; $('#mfaConfirmForm').reset(); }
    $$('#tab-security input[type=password]').forEach(field => { field.value = ''; });
    $$('#tab-staff input[type=password]').forEach(field => { field.value = ''; });
  }

  async function submitting(form, work) {
    const button = $('button[type=submit]', form);
    if (button?.disabled) return;
    if (button) button.disabled = true;
    try { await work(); }
    catch (error) { context.toast(message(error)); }
    finally {
      $$('input[type=password]', form).forEach(field => { field.value = ''; });
      if (button) button.disabled = false;
    }
  }

  async function loadStaff() {
    $('#staffAccounts').innerHTML = '<p class="loading" role="status">Загрузка сотрудников…</p>';
    try {
      const data = await context.api('/api/admin/staff');
      $('#staffCreateRole').innerHTML = roleOptions(data.roles, 'content_editor');
      $('#bootstrapOwnerNotice').textContent = data.bootstrap_owner
        ? 'Учётная запись owner подключена через настройки окружения и не входит в список ниже.'
        : 'Bootstrap-владелец через окружение не настроен.';
      $('#staffAccounts').innerHTML = data.accounts.length ? data.accounts.map(account => {
        const editable = account.id !== context.principal.id && (context.principal.role === 'owner' || !['owner','admin'].includes(account.role));
        const options = editable ? roleOptions(data.roles, account.role) : `<option>${esc(roles[account.role] || account.role)}</option>`;
        return `<article class="staff-account" data-staff-id="${esc(account.id)}"><div class="staff-account-head"><div><h3>${esc(account.username)}</h3><p>${account.active ? 'Доступ открыт' : 'Заблокирован'} · MFA ${account.mfa_enabled ? 'подключена' : 'не подключена'}${account.id === context.principal.id ? ' · ваша учётная запись' : ''}</p></div></div><label>Роль<select data-staff-role ${editable ? '' : 'disabled'}>${options}</select></label>${editable ? `<div class="staff-actions"><button type="button" class="btn btn-outline" data-staff-save>Сохранить роль</button><button type="button" class="btn btn-outline" data-staff-toggle data-active="${account.active ? 'false' : 'true'}">${account.active ? 'Заблокировать' : 'Открыть доступ'}</button></div><form class="staff-reset-form"><label>Новый пароль сотрудника<input type="password" name="password" minlength="12" maxlength="256" required autocomplete="new-password"></label><button type="submit" class="btn btn-outline">Сбросить пароль</button></form>` : '<p class="fine-print">Изменение этой учётной записи здесь недоступно.</p>'}</article>`;
      }).join('') : '<p class="empty-state">Отдельных сотрудников пока нет. Создайте первую учётную запись.</p>';
      $$('#staffAccounts [data-staff-save]').forEach(button => button.addEventListener('click', () => accountAction(button, {role:$('select', button.closest('[data-staff-id]')).value})));
      $$('#staffAccounts [data-staff-toggle]').forEach(button => button.addEventListener('click', () => accountAction(button, {active:button.dataset.active === 'true'})));
      $$('#staffAccounts .staff-reset-form').forEach(form => form.addEventListener('submit', event => {
        event.preventDefault(); submitting(form, async () => {
          const id = form.closest('[data-staff-id]').dataset.staffId;
          await context.api(`/api/admin/staff/${encodeURIComponent(id)}`, {method:'PATCH', body:JSON.stringify({password:form.elements.password.value})});
          context.toast('Пароль обновлён. Сессии сотрудника завершены.');
        });
      }));
      await loadLoginEvents();
    } catch (error) { $('#staffAccounts').innerHTML = `<p class="alert" role="alert">${esc(message(error))}</p>`; }
  }

  async function accountAction(button, payload) {
    button.disabled = true;
    try {
      const id = button.closest('[data-staff-id]').dataset.staffId;
      await context.api(`/api/admin/staff/${encodeURIComponent(id)}`, {method:'PATCH', body:JSON.stringify(payload)});
      context.toast('Доступ обновлён. Прежние сессии сотрудника завершены.');
      await loadStaff();
    } catch (error) { context.toast(message(error)); button.disabled = false; }
  }

  async function loadLoginEvents() {
    try {
      const data = await context.api('/api/admin/security/login-events');
      const outcomes = {success:'Вход выполнен', denied:'Отказ', throttled:'Ограничение попыток', mfa_enrollment_required:'Требуется MFA'};
      $('#staffLoginEvents').innerHTML = data.events.length ? data.events.map(row => `<tr><td>${esc(when(row.created_at))}</td><td>${esc(outcomes[row.outcome] || row.outcome)}</td><td><code>${esc(row.subject_hash.slice(0,16))}…</code></td></tr>`).join('') : '<tr><td colspan="3">Событий входа пока нет.</td></tr>';
    } catch (error) { $('#staffLoginEvents').innerHTML = `<tr><td colspan="3">${esc(message(error))}</td></tr>`; }
  }

  async function loadSecurity() {
    clearSecrets();
    $('#staffSessions').innerHTML = '<p class="loading" role="status">Загрузка сессий…</p>';
    try {
      const [principal, data] = await Promise.all([context.api('/api/admin/security/me'), context.api('/api/admin/security/sessions')]);
      context.principal = principal;
      $('#personalIdentity').textContent = `${principal.username} · ${roles[principal.role] || principal.role}`;
      $('#personalMfaStatus').textContent = principal.mfa_enabled ? 'MFA подключена' : 'MFA ещё не подключена';
      $('#mfaEnrollForm').hidden = principal.mfa_enabled;
      $('#personalPasswordForm').hidden = principal.id === 'bootstrap';
      $('#bootstrapPasswordNotice').hidden = principal.id !== 'bootstrap';
      $('#staffSessions').innerHTML = data.sessions.length ? data.sessions.map(row => `<article class="session-item"><div><b>${row.current ? 'Текущий сеанс' : 'Другой сеанс'}</b><p>Открыт: ${esc(when(row.created_at))}<br>Истекает: ${esc(when(row.expires_at))}${row.revoked_at ? `<br>Завершён: ${esc(when(row.revoked_at))}` : ''}</p></div>${row.revoked_at ? '<span>Завершён</span>' : `<button type="button" class="btn btn-outline" data-revoke-session="${esc(row.id)}" data-current="${row.current ? 'true' : 'false'}">Завершить${row.current ? ' текущий' : ''} сеанс</button>`}</article>`).join('') : '<p class="empty-state">Активных сессий нет.</p>';
      $$('[data-revoke-session]').forEach(button => button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          await context.api(`/api/admin/security/sessions/${encodeURIComponent(button.dataset.revokeSession)}`, {method:'DELETE'});
          if (button.dataset.current === 'true') { clearSecrets(); location.assign('/admin/login'); return; }
          context.toast('Сеанс завершён.'); await loadSecurity();
        } catch (error) { context.toast(message(error)); button.disabled = false; }
      }));
    } catch (error) { $('#staffSessions').innerHTML = `<p class="alert" role="alert">${esc(message(error))}</p>`; }
  }

  function mount(options) {
    context = options;
    $('#staffCreateForm')?.addEventListener('submit', event => {
      event.preventDefault(); const form = event.currentTarget;
      submitting(form, async () => {
        await context.api('/api/admin/staff', {method:'POST', body:JSON.stringify({username:form.elements.username.value, password:form.elements.password.value, role:form.elements.role.value})});
        form.reset(); context.toast('Учётная запись создана.'); await loadStaff();
      });
    });
    $('#refreshStaff')?.addEventListener('click', loadStaff);
    $('#refreshSessions')?.addEventListener('click', loadSecurity);
    $('#personalPasswordForm').addEventListener('submit', event => {
      event.preventDefault(); const form = event.currentTarget;
      submitting(form, async () => {
        if (form.elements.new_password.value !== form.elements.confirm_password.value) throw new Error('Новые пароли не совпадают.');
        await context.api('/api/admin/security/password', {method:'POST', body:JSON.stringify({password:form.elements.password.value, new_password:form.elements.new_password.value})});
        clearSecrets(); location.assign('/admin/login');
      });
    });
    $('#mfaEnrollForm').addEventListener('submit', event => {
      event.preventDefault(); const form = event.currentTarget;
      submitting(form, async () => {
        const data = await context.api('/api/admin/security/mfa/enroll', {method:'POST', body:JSON.stringify({password:form.elements.password.value})});
        $('#mfaSecret').textContent = data.secret;
        $('#mfaHideSecret').hidden = false;
        $('#mfaProvisioning').hidden = false;
        $('#mfaConfirmForm [name=code]').focus();
        clearTimeout(secretTimer); secretTimer = setTimeout(clearSecrets, Number(data.expires_in) * 1000);
        context.toast('Введите секрет в аутентификатор и подтвердите код.');
      });
    });
    $('#mfaConfirmForm').addEventListener('submit', event => {
      event.preventDefault(); const form = event.currentTarget;
      submitting(form, async () => {
        await context.api('/api/admin/security/mfa/confirm', {method:'POST', body:JSON.stringify({code:form.elements.code.value})});
        clearSecrets(); context.toast('MFA подключена. Для следующего входа понадобится новый код.'); await loadSecurity();
      });
    });
    $('#mfaHideSecret').addEventListener('click', event => {
      $('#mfaSecret').textContent = 'Секрет скрыт';
      event.currentTarget.hidden = true;
      $('#mfaConfirmForm [name=code]').focus();
    });
    window.addEventListener('pagehide', clearSecrets);
  }

  window.RakovarStaff = {mount, loadStaff, loadSecurity, clearSecrets, roles};
})();

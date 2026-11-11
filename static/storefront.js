(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const money = n => new Intl.NumberFormat('ru-RU').format(Number(n || 0)) + ' ₽';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const guestKey = 'rakovar_demo_guest';
  const cartKey = 'rakovar_demo_cart';
  function browserStorage(name) {
    try { return window[name]; }
    catch { const values = new Map(); return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }; }
  }
  const local = browserStorage('localStorage');
  const tabStorage = browserStorage('sessionStorage');
  const spinRequests = new window.RakovarWheel.PendingRequests(local);
  const orderRequests = new window.RakovarWheel.PendingRequests(tabStorage);
  const state = { products: [], csrf: '', guestId: '', cart: {}, category: 'all', search: '', sort: 'popular', catalogLimit: 24, promo: '', delivery: 'delivery', contests: [], referral: null, maxStartParam: '', spinning: false, orderBusy: false, wheel: null, tickets: 0 };
  let modalReturnFocus = null;
  let cartReturnFocus = null;

  function getGuestId() {
    let id;
    try { id = local.getItem(guestKey); } catch { /* A new session can still be used. */ }
    if (!id) {
      id = window.RakovarWheel.secureKey();
      try { local.setItem(guestKey, id); } catch { /* Browser storage is optional. */ }
    }
    return id;
  }
  async function api(url, options = {}) {
    const headers = { ...(options.body ? {'Content-Type':'application/json'} : {}), ...(options.headers || {}) };
    if (options.method && options.method !== 'GET' && state.csrf) headers['X-CSRF-Token'] = state.csrf;
    const res = await fetch(url, { credentials: 'same-origin', ...options, headers });
    let data;
    try { data = await res.json(); }
    catch { const error = new Error('Не удалось подтвердить результат. Повторите с теми же данными.'); error.status = res.status; error.retryable = true; throw error; }
    if (!res.ok) {
      const messages={invalid_checkout:'Проверьте имя, телефон и согласие на обработку заказа.',address_required:'Укажите полный адрес доставки.',invalid_quantity_step:'Выберите количество с допустимым шагом.',store_temporarily_closed:'Приём заказов временно приостановлен.',reward_already_used:'Этот подарочный код уже применён к заказу.',promotion_not_available:'Промокод недоступен. Проверьте его условия или удалите код.',delivery_reward_requires_delivery:'Подарок действует для доставки. Выберите доставку или уберите код.',gift_out_of_stock:'Подарок закончился. Уберите код или выберите другое предложение.',gift_not_configured:'Подарок временно недоступен. Уберите код для оформления.',csrf_failed:'Сессия устарела. Обновите страницу.',insufficient_stock:'Остаток изменился. Уменьшите количество.'};
      const error = new Error(messages[data?.error] || data?.message || data?.error || `Ошибка ${res.status}`);
      error.status = res.status; error.code = data?.error;
      error.retryable = res.status >= 500 || res.status === 429 || data?.error === 'idempotency_in_progress';
      throw error;
    }
    return data;
  }
  const requestScope = operation => `${operation==='order'?'store_order':operation}:${state.guestId}`;
  async function sendOnce(operation, url, payload, validate) {
    const requests = operation === 'spin' ? spinRequests : orderRequests;
    const scope = requestScope(operation);
    const pending = await requests.prepare(scope, payload);
    try {
      const result = await api(url, { method: 'POST', headers: { 'Idempotency-Key': pending.key }, body: JSON.stringify(payload) });
      if (!validate(result)) { const error = new Error('Не удалось подтвердить результат. Повторите с теми же данными.'); error.retryable = true; throw error; }
      requests.clear(scope, pending.key);
      return result;
    } catch (error) {
      if (error.status >= 400 && error.status < 500 && !error.retryable) requests.clear(scope, pending.key);
      throw error;
    }
  }
  function toast(message) {
    const node = $('#toast'); node.textContent = message; node.classList.add('show');
    clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('show'), 3000);
  }
  function track(name, metadata = {}) {
    api('/api/events', { method:'POST', body:JSON.stringify({ event:name, guest_id:state.guestId, metadata }) }).catch(() => {});
  }
  function loadCart() {
    try { state.cart = JSON.parse(local.getItem(cartKey) || '{}') || {}; } catch { state.cart = {}; }
  }
  function saveCart() { try { local.setItem(cartKey, JSON.stringify(state.cart)); } catch { /* The current-page cart remains usable. */ } }
  function productById(id) { return state.products.find(p => p.id === id); }
  function cartItems() {
    return Object.entries(state.cart).map(([id, quantity]) => ({ id, quantity })).filter(x => productById(x.id) && x.quantity > 0);
  }
  function cartCount() { return cartItems().length; }
  function syncBackgroundAccess() {
    const blocked = !$('#modal').hidden || !$('#cartBackdrop').hidden;
    $$('.site-header,main,.site-footer').forEach(node => { node.inert = blocked; });
    $('#cartBackdrop').inert = !$('#modal').hidden;
  }
  function openModal(html) {
    modalReturnFocus = document.activeElement;
    $('#modalContent').innerHTML = html; $('#modal').hidden = false;
    syncBackgroundAccess();
    ($('#modalContent').querySelector('button,input,textarea,a[href]') || $('#modalClose')).focus();
  }
  function closeModal() {
    $('#modal').hidden = true; $('#modalContent').innerHTML = ''; syncBackgroundAccess();
    if (modalReturnFocus?.isConnected) modalReturnFocus.focus();
  }
  function openCart() {
    cartReturnFocus = document.activeElement; $('#cartBackdrop').hidden = false; syncBackgroundAccess(); $('#cartClose').focus();
  }
  function closeCart() {
    $('#cartBackdrop').hidden = true; syncBackgroundAccess();
    if (cartReturnFocus?.isConnected) cartReturnFocus.focus();
  }

  function applySiteSettings(settings = {}) {
    if (settings.hero_title && settings.hero_title !== 'Море ближе, чем кажется.') $('#heroTitle').textContent = settings.hero_title;
    if (settings.hero_text) $('#heroText').textContent = settings.hero_text;
    if (settings.hero_cta) $('#heroCta').textContent = settings.hero_cta;
    if (settings.promo_title && settings.promo_title !== 'Вместо обычного букета — морские деликатесы.') $('#promoTitle').textContent = settings.promo_title;
    if (settings.promo_text) $('#promoText').textContent = settings.promo_text;
    if (settings.footer_notice) $('#footerNotice').textContent = settings.footer_notice;
  }
  function renderCategories() {
    const order = ['Раки','Сеты','Креветки','Мидии и моллюски','Лангустины','Живые раки','Рыба','Сезонное','Подарки','Деликатесы','Комбо','Закуски','Бургеры','Соусы'];
    const rank = category => order.includes(category) ? order.indexOf(category) : order.length;
    const cats = ['all', ...[...new Set(state.products.map(p => p.category))].sort((a,b) => rank(a)-rank(b) || a.localeCompare(b,'ru'))];
    $('#categories').innerHTML = cats.map(c => `<button class="chip ${state.category === c ? 'active' : ''}" data-category="${esc(c)}">${c === 'all' ? 'Всё' : esc(c)}</button>`).join('');
    $$('#categories [data-category]').forEach(btn => btn.addEventListener('click', () => { state.category = btn.dataset.category; state.catalogLimit=24; renderCategories(); renderProducts(); }));
  }
  function renderProducts() {
    let list = [...state.products].filter(p => (state.category === 'all' || p.category === state.category) && `${p.title} ${p.description}`.toLowerCase().includes(state.search.toLowerCase()));
    if (state.sort === 'popular') {
      const picks = ['crayfish-medium-kg','set-4-morya','shrimp-assorted-fried','mussels-wine','set-firmenny','dorado-grill','live-crayfish-request','edible-bouquet-request'];
      const rank = product => picks.includes(product.id) ? picks.indexOf(product.id) : picks.length;
      list.sort((a,b) => rank(a)-rank(b));
    }
    if (state.sort === 'price-asc') list.sort((a,b) => Number(!!a.price_on_request)-Number(!!b.price_on_request) || a.price-b.price);
    if (state.sort === 'price-desc') list.sort((a,b) => Number(!!a.price_on_request)-Number(!!b.price_on_request) || b.price-a.price);
    if (state.sort === 'title') list.sort((a,b) => a.title.localeCompare(b.title, 'ru'));
    const total=list.length; list=list.slice(0,state.catalogLimit);
    $('#catalogMore').hidden=state.catalogLimit>=total;
    $('#catalogMore').textContent='Показать ещё '+Math.min(24,Math.max(0,total-state.catalogLimit))+' позиций';
    $('#products').innerHTML = list.length ? list.map(p => {
      const fallback = `/static/images/${(p.image || 'opt_hero.svg').split('/').map(encodeURIComponent).join('/')}`;
      const photo = p.image_url ? esc(p.image_url) : fallback;
      const priceNote = esc(p.unit);
      const priceLabel = money(p.price);
      const stockNote = p.weight_label ? esc(p.weight_label) : '';
      const action = `<button class="add-button" data-add="${esc(p.id)}" ${p.stock<=0?'disabled':''}>${p.stock<=0?'Нет в наличии':'В корзину +'}</button>`;
      return `<article class="product-card">
      <div class="product-image"><img loading="lazy" src="${photo}" data-fallback="${fallback}" alt="${esc(p.title)}"><span class="product-badge">${esc(p.badge || 'РАКОВАРЪ')}</span><button class="product-favorite" data-favorite="${esc(p.id)}" aria-pressed="${state.customer?.favorites.includes(p.id)?'true':'false'}" aria-label="В избранное: ${esc(p.title)}">${state.customer?.favorites.includes(p.id)?'♥':'♡'}</button></div>
      <div class="product-body"><div class="product-meta"><span>${esc(p.category)}</span><span>${stockNote}</span></div><h3>${esc(p.title)}</h3><p>${esc(p.description)}</p><button type="button" class="product-details" data-details="${esc(p.id)}">Состав и подробности</button>
      <small class="product-availability">${esc(p.availability||'Под заказ')}</small><div class="product-foot"><div class="price"><strong>${priceLabel}</strong><small>${priceNote}</small></div>${action}</div></div></article>`;
    }).join('') : '<div class="empty-state">Ничего не найдено. Попробуйте изменить запрос.</div>';
    $$('[data-favorite]').forEach(b=>b.onclick=async()=>{if(state.favoriteBusy)return;state.favoriteBusy=true;const id=b.dataset.favorite;const favorites=state.customer.favorites.includes(id)?state.customer.favorites.filter(x=>x!==id):[...state.customer.favorites,id];try{await api('/api/store/profile',{method:'PUT',body:JSON.stringify({favorites})});state.customer.favorites=favorites;renderProducts();toast(favorites.includes(id)?'Сохранено в избранном':'Убрано из избранного');}catch(error){toast(error.message);}finally{state.favoriteBusy=false;}});
    $$('[data-add]').forEach(btn => btn.addEventListener('click', () => addToCart(btn.dataset.add)));
    $$('[data-details]').forEach(btn=>btn.addEventListener('click',()=>{
      const p=productById(btn.dataset.details);if(!p)return;
      openModal(`<div class="product-dialog"><img src="${esc(window.RakovarStudio.image(p))}" alt="${esc(p.title)}"><div class="eyebrow">${esc(p.category)}${p.weight_label?' · '+esc(p.weight_label):''}</div><h3>${esc(p.title)}</h3><p>${esc(p.description)}</p><p>${p.ingredients?esc(p.ingredients):'Пожелания к приготовлению, состав и аллергены уточните у администратора перед заказом.'}</p><strong>${money(p.price)+' · '+esc(p.unit)}</strong><button type="button" class="btn btn-primary btn-wide" id="detailToSet">Добавить в мой сет</button></div>`);
      $('#detailToSet').onclick=()=>{state.studio?.select(p.id);closeModal();document.querySelector('#sets').scrollIntoView({behavior:'smooth'});};
    }));
    $$('#products img[data-fallback]').forEach(img => img.addEventListener('error', () => { img.src = img.dataset.fallback; }, { once: true }));
  }
  function addBatch(rows){
    const combined={...state.cart};
    for(const row of rows){const p=productById(row.id),qty=Math.round(((combined[row.id]||0)+row.quantity)*1000)/1000;if(!p||qty>Math.min(50,p.stock))return toast('Проверьте количество и наличие выбранных блюд.');combined[row.id]=qty;}
    if(Object.keys(combined).length>30)return toast('В одном заказе доступно до 30 разных позиций.');
    state.cart=combined;saveCart();updateCart();toast('Добавлено в корзину.');openCart();
  }
  function renderBuilder() {
    state.studio = window.RakovarStudio.mount(state.products,{toast,addBatch});
    window.RakovarStudio.mountLive(state.products,{toast,addBatch});
    $('#sets').hidden=state.storeRules?.builder_enabled===false;
    $('#contests').hidden=state.storeRules?.contests_visible!==true;document.querySelectorAll('a[href="#contests"]').forEach(link=>link.hidden=state.storeRules?.contests_visible!==true);
  }
  function addToCart(id, qty = null) {
    const p = productById(id); if (!p) return;
    qty ??= p.quantity_step || 1;
    const next = Math.round(((state.cart[id] || 0) + qty)*1000)/1000;
    if (next > p.stock) { toast('Такое количество сейчас недоступно. Уточните у администратора.'); return; }
    state.cart[id] = next; saveCart(); updateCart(); track('add_to_cart', { product_id:id, quantity:qty }); toast('Добавлено в корзину');
  }
  function updateCart() {
    const items=cartItems();$('#cartCount').textContent=cartCount();
    $('#cartItems').innerHTML=items.length?items.map(({id,quantity})=>{const p=productById(id);return `<div class="cart-line"><img class="cart-photo" src="${esc(window.RakovarStudio.image(p))}" alt="${esc(p.title)}"><div class="cart-product-copy"><b>${esc(p.title)}</b><small>${money(p.price)} · ${esc(p.unit)} · ${money(Math.round(p.price*quantity))}</small><button type="button" class="cart-remove" data-remove-cart="${esc(id)}">Убрать</button></div><div class="qty-control"><button type="button" data-dec="${esc(id)}" aria-label="Уменьшить ${esc(p.title)}">−</button><b>${quantity}</b><button type="button" data-inc="${esc(id)}" aria-label="Увеличить ${esc(p.title)}">+</button></div></div>`;}).join(''):'<div class="empty-state">Корзина пока пуста. Выберите что-нибудь вкусное.</div>';
    $$('[data-dec]').forEach(b=>b.onclick=()=>changeQty(b.dataset.dec,-1));$$('[data-inc]').forEach(b=>b.onclick=()=>changeQty(b.dataset.inc,1));$$('[data-remove-cart]').forEach(b=>b.onclick=()=>{delete state.cart[b.dataset.removeCart];saveCart();updateCart();});
    const sauces=state.products.filter(p=>p.category==='Соусы'&&!state.cart[p.id]&&p.stock>0).slice(0,3);$('#cartUpsell').innerHTML=items.length&&sauces.length?'<h4>Дополнить вечер</h4><div class="cart-upsell-grid">'+sauces.map(p=>`<div class="cart-upsell-item"><img src="${esc(window.RakovarStudio.image(p))}" alt="${esc(p.title)}"><b>${esc(p.title)}</b><span>${money(p.price)}</span><button type="button" data-upsell="${esc(p.id)}">Добавить +</button></div>`).join('')+'</div>':'';$$('[data-upsell]').forEach(b=>b.onclick=()=>addToCart(b.dataset.upsell));
    $('#deliveryAddressGroup').hidden=state.delivery!=='delivery';$('#customerAddress').required=state.delivery==='delivery';
    quoteCart();
  }
  function changeQty(id,direction){const p=productById(id);if(!p)return;const next=Math.round(((state.cart[id]||0)+direction*(p.quantity_step||1))*1000)/1000;if(next<=0)delete state.cart[id];else if(next<=p.stock)state.cart[id]=next;else toast('Доступное количество ограничено.');saveCart();updateCart();}
  async function quoteCart(){
    const version=(state.quoteVersion||0)+1;state.quoteVersion=version;const items=cartItems();const submit=$('#checkoutForm button[type="submit"]');submit.disabled=true;
    if(!items.length){$('#subtotal').textContent=money(0);$('#discount').textContent=money(0);$('#deliveryCost').textContent=money(0);$('#total').textContent=money(0);$('#cartGiftPreview').textContent='';return;}
    try{
      const q=await api('/api/store/quote',{method:'POST',body:JSON.stringify({items,promo_code:state.promo,delivery_mode:state.delivery,bonus_spend:Number($('#bonusSpend').value)||0})});if(version!==state.quoteVersion)return;
      state.quote=q;$('#cartGiftPreview').innerHTML=q.items.filter(i=>i.gift).map(i=>`<div class="bonus-checkout"><b>Подарок: ${esc(i.title)}</b><small>Добавлен бесплатно по вашему коду</small></div>`).join('');$('#subtotal').textContent=money(q.subtotal_rub);$('#discount').textContent='−'+money(q.discount_rub+q.bonus_spent);$('#deliveryCost').textContent=money(q.delivery_rub);$('#total').textContent=money(q.total_rub);$('#bonusSpend').max=q.bonus_max;
      $('#bonusCheckoutHint').textContent=`На счёте ${q.bonus_available} баллов. Для этого заказа доступно ${q.bonus_max}. Вернём ${q.bonus_earned} после подтверждения оплаты.`;
      $('#promoMessage').textContent=state.promo?(q.promo_valid?'Применён: '+q.promo_message:q.promo_message):'';submit.disabled=state.orderBusy||!state.storeRules?.accepting_orders;
    }catch(error){if(version!==state.quoteVersion)return;const messages={delivery_min_order:'Для доставки нужна сумма от '+money(state.storeRules?.delivery_minimum||0)+'. Добавьте блюда или выберите самовывоз.',bonus_limit_exceeded:'Сумма списания превышает доступные бонусы. Уменьшите её.',insufficient_stock:'Остаток изменился. Уменьшите количество товара.'};$('#promoMessage').textContent=messages[error.code]||error.message;if(orderRequests.read(requestScope('order'))&&!state.orderBusy){submit.disabled=false;$('#checkoutRetry').textContent='Есть неподтверждённая отправка. Повторите исходный запрос или проверьте заказ в кабинете.';}}
  }
  function renderOffers(rows){$('#publicPromotions').innerHTML=rows.length?rows.map(p=>`<article class="offer-card"><span class="eyebrow">${p.discount_type==='percent'?p.discount_value+'%':money(p.discount_value)} ДЛЯ ВАС</span><h3>${esc(p.title)}</h3><p>${esc(p.description)}</p><small>От ${money(p.min_order)}${p.ends_at?' · до '+esc(p.ends_at):''}${p.ticket_reward?' · '+p.ticket_reward+' клубный билет':''}</small><div class="offer-code"><b>${esc(p.code)}</b><button type="button" data-offer="${esc(p.code)}">Применить ↗</button></div></article>`).join(''):'<p class="fine-print">Новые предложения появятся здесь. Бонусы за покупки доступны в вашем кабинете.</p>';$$('[data-offer]').forEach(b=>b.onclick=()=>{state.promo=b.dataset.offer;$('#promoCode').value=state.promo;quoteCart();toast('Промокод добавлен к вашему заказу.');});}
  function renderPrizes(prizes) {
    const icons = { coupon:'％', delivery:'↗', gift:'🎁', points:'✦' };
    $('#prizeList').innerHTML = prizes.length ? prizes.map(p => `<div class="prize-row"><span class="prize-emoji">${icons[p.kind] || '🎁'}</span><div><b>${esc(p.title)}</b><small>${esc(p.partner || 'Партнёр')} · ${esc(p.description)}</small></div></div>`).join('') : '<div class="empty-state">Призы пока не добавлены.</div>';
  }
  async function refreshGame() {
    const p = await api(`/api/game/profile?guest_id=${encodeURIComponent(state.guestId)}`);
    state.tickets = Number(p.tickets);
    $('#ticketBalance').textContent = p.tickets;
    $('#headerTicketBalance')?.remove();
    const history = await api(`/api/game/history?guest_id=${encodeURIComponent(state.guestId)}`);
    $('#gameHistory').textContent = history.length ? 'Последние результаты: ' + history.slice(0,3).map(x => x.prize_title + (x.redemption_code ? ` [${x.redemption_code}]` : '')).join(' · ') : 'Здесь появится история ваших вращений.';
    updateSpinButton();
  }
  function updateSpinButton() {
    const pending = Boolean(spinRequests.read(requestScope('spin')));
    const btn = $('#spinButton');
    btn.disabled = state.spinning || !state.wheel?.sectors.length || (!pending && state.tickets < 1);
    btn.setAttribute('aria-busy', String(state.spinning));
    btn.textContent = state.spinning ? 'Определяем результат…' : pending ? 'Повторить запрос результата' : state.tickets < 1 ? 'Нет клубных билетов' : 'Использовать билет ↗';
  }
  async function refreshReferral() {
    const data = await api(`/api/referrals/profile?guest_id=${encodeURIComponent(state.guestId)}`);
    state.referral = data;
    $('#referralCode').textContent = data.code;
    $('#referralStats').textContent = `Приглашено: ${data.total} · Выполнили условие: ${data.qualified} · Ожидают покупки: ${data.pending}`;
    $('#referrerReward').textContent = `${data.rules.referrer_tickets} билетов`;
    $('#friendReward').textContent = `${data.rules.friend_tickets} билетов`;
    $('#referralTier').textContent = `Уровень «${data.tier.name}» · покупки за 365 дней: ${money(data.tier.spend_365d)}. ${data.tier.next_tier ? `До уровня «${data.tier.next_tier}»: ${money(data.tier.to_next_tier)}.` : 'Достигнут высший уровень.'}`;
  }
  async function attachReferralFromUrl() {
    const queryCode = new URLSearchParams(location.search).get('ref');
    const startCode = state.maxStartParam.startsWith('ref_') ? state.maxStartParam.slice(4) : '';
    const code = queryCode || startCode;
    if (!code) return;
    try {
      const result = await api('/api/referrals/attach', { method:'POST', body:JSON.stringify({ guest_id:state.guestId, code }) });
      toast(result.message);
      history.replaceState({}, '', location.pathname + location.hash);
    } catch (error) {
      if (!['referral_already_attached','referral_not_new_customer'].includes(error.message)) toast(error.message);
      history.replaceState({}, '', location.pathname + location.hash);
    }
  }
  async function spin() {
    if (state.spinning || !state.wheel?.sectors.length) return;
    state.spinning = true; updateSpinButton(); $('#spinRetry').textContent = '';
    try {
      const result = await sendOnce('spin', '/api/game/spin', { guest_id:state.guestId }, window.RakovarWheel.validSpinResult);
      state.tickets = Number(result.tickets); $('#ticketBalance').textContent = result.tickets;
      await state.wheel.reveal(result);
      openModal(`<div class="eyebrow">ВАШ РЕЗУЛЬТАТ</div><h3>Поздравляем!</h3><p style="font:700 25px var(--serif);color:var(--gold2)">${esc(result.prize.title)}</p><p>${esc(result.prize.description)}</p>${result.redemption_code?`<p>Код результата: <b style="color:var(--gold2)">${esc(result.redemption_code)}</b></p>`:''}<p class="fine-print">${esc(result.message)}</p><button class="btn btn-primary btn-wide" id="prizeModalOk">Отлично</button>`);
      $('#prizeModalOk').addEventListener('click', closeModal);
      refreshGame().catch(() => { $('#gameHistory').textContent = 'Результат сохранён. История обновится при следующем открытии.'; });
    } catch (error) {
      const pending = spinRequests.read(requestScope('spin'));
      $('#spinRetry').textContent = pending ? 'Не удалось получить ответ. Попробуйте ещё раз — второй билет за это вращение не спишется.' : error.message;
      state.wheel.status.textContent = error.message; toast(error.message);
    }
    finally { state.spinning = false; updateSpinButton(); }
  }
  function renderContests(contests) {
    state.contests = contests;
    $('#contestList').innerHTML = contests.length ? contests.map(c => `<article class="contest-card"><span class="tiny-label">АКТИВНОСТЬ · ДО ${esc(c.ends_at)}</span><h3>${esc(c.title)}</h3><p>${esc(c.description)}</p><div class="contest-prize">Приз: ${esc(c.prize_title)}</div><p class="fine-print">${esc(c.rules)}</p><div class="contest-actions"><button class="btn btn-outline" data-enter-contest="${esc(c.id)}">Попробовать участие</button><button class="btn btn-ghost" data-share-contest="${esc(c.id)}">Поделиться</button></div></article>`).join('') : '<div class="empty-state">Активных конкурсов сейчас нет.</div>';
    $$('[data-enter-contest]').forEach(btn => btn.addEventListener('click', () => contestModal(btn.dataset.enterContest)));
    $$('[data-share-contest]').forEach(btn => btn.addEventListener('click', () => shareContest(btn.dataset.shareContest)));
  }
  async function shareContest(id) {
    const c=state.contests.find(x=>x.id===id); if(!c) return;
    const link=`${window.location.origin}/#club`;
    const text=`🦞 РАКОВАРЪ · ${c.title}\nПриз: ${c.prize_title}\nУчаствуйте в клубной активности!`;
    try {
      if(window.WebApp?.shareMaxContent) await window.WebApp.shareMaxContent({text,link});
      else if(navigator.share) await navigator.share({title:c.title,text,url:link});
      else { await navigator.clipboard.writeText(`${text}\n${link}`); toast('Ссылка на конкурс скопирована.'); }
    } catch(error) { if(error?.name!=='AbortError') toast('Не удалось открыть меню отправки.'); }
  }
  function contestModal(id) {
    const c = state.contests.find(x => x.id === id); if (!c) return;
    openModal(`<div class="eyebrow">ВАША ИДЕЯ</div><h3>${esc(c.title)}</h3><p>${esc(c.description)}</p><form id="contestEntryForm"><label class="tiny-label">Ваше имя / псевдоним</label><input name="alias" minlength="2" maxlength="40" required placeholder="Например, Морской гурман"><label class="tiny-label">Почему вам нравится такая идея?</label><textarea name="answer" minlength="5" maxlength="500" required placeholder="Короткий ответ"></textarea><button class="btn btn-primary btn-wide" type="submit">Сохранить идею</button></form><p class="fine-print">Не указывайте контактные данные. Участие ознакомительное, призы пока не выдаются.</p>`);
    $('#contestEntryForm').addEventListener('submit', async e => {
      e.preventDefault(); const f = new FormData(e.currentTarget);
      try { const r = await api(`/api/contests/${encodeURIComponent(id)}/entries`, { method:'POST', body:JSON.stringify({ guest_id:state.guestId, alias:f.get('alias'), answer:f.get('answer') }) }); closeModal(); await refreshGame(); toast(r.tickets_awarded ? `${r.message} Начислено билетов: ${r.tickets_awarded}.` : r.message); track('contest_entry',{contest_id:id}); }
      catch (err) { toast(err.message); }
    });
  }
  function bindEvents() {
    $('#catalogMore').addEventListener('click',()=>{state.catalogLimit+=24;renderProducts();});
    $('#search').addEventListener('input', e => { state.catalogLimit=24; state.search=e.target.value; renderProducts(); });
    $('#sort').addEventListener('change', e => { state.sort=e.target.value; renderProducts(); });
    $('#cartOpen').addEventListener('click', () => { openCart(); updateCart(); track('checkout_started'); });
    $('#cartClose').addEventListener('click', closeCart);
    $('#cartBackdrop').addEventListener('click', e => { if (e.target.id === 'cartBackdrop') closeCart(); });
    $('#modalClose').addEventListener('click', closeModal); $('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });
    document.addEventListener('keydown', e => {
      const panel = !$('#modal').hidden ? $('#modal .modal-panel') : !$('#cartBackdrop').hidden ? $('.cart-drawer') : null;
      if (!panel) return;
      if (e.key === 'Escape') { e.preventDefault(); !$('#modal').hidden ? closeModal() : closeCart(); return; }
      if (e.key !== 'Tab') return;
      const focusable = [...panel.querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]')].filter(node => !node.hidden && node.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (e.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) { e.preventDefault(); first?.focus(); }
    });
    $$('input[name="delivery"]').forEach(el => el.addEventListener('change', () => { state.delivery=el.value; updateCart(); }));
    $('#bonusSpend').addEventListener('input',()=>quoteCart());
    $('#applyPromo').addEventListener('click', () => { state.promo=$('#promoCode').value.trim().toUpperCase(); quoteCart(); track('promo_applied',{code:state.promo}); });
    $('#checkoutForm').addEventListener('submit', async e => {
      e.preventDefault(); if (state.orderBusy) return;
      if (!cartItems().length) return toast('Сначала добавьте товары в корзину.');
      const form = e.currentTarget;
      const btn = e.submitter || form.querySelector('button[type="submit"]');
      const label = btn.textContent;
      state.orderBusy = true; btn.disabled = true; btn.setAttribute('aria-busy', 'true'); btn.textContent = 'Сохраняем заказ…';
      $('#checkoutRetry').textContent = '';
      try {
        const result = await sendOnce('order', '/api/store/orders', { guest_id:state.guestId, items:cartItems(), promo_code:state.promo, delivery_mode:state.delivery, name:$('#customerName').value, phone:$('#customerPhone').value, address:$('#customerAddress').value, comment:$('#customerComment').value, payment_method:$('#customerPayment').value, bonus_spend:Number($('#bonusSpend').value)||0, save_profile:$('#saveCustomerProfile').checked, consent:$('#consent').checked }, data => typeof data?.order_id === 'string' && data.status === 'order_created' && Number.isFinite(data.total_rub));
        state.cart={}; saveCart(); closeCart(); form.reset(); state.promo=''; $('#promoCode').value=''; state.delivery = form.querySelector('input[name="delivery"]:checked')?.value || 'delivery'; updateCart();
        openModal(`<div class="eyebrow">ЗАКАЗ ПОЛУЧЕН</div><h3>Ваш вечер почти готов</h3><p style="font:700 24px var(--serif);color:var(--gold2)">${esc(result.order_id)}</p><p>${esc(result.message)}</p><p>Сумма заказа: <b>${money(result.total_rub)}</b></p><div class="order-success-links"><a class="btn btn-outline" href="/account">Следить за заказом ↗</a></div><button class="btn btn-primary btn-wide" id="orderDone">Вернуться на витрину</button>`);
        $('#orderDone').addEventListener('click',closeModal); toast('Заказ сохранён. Статус доступен в вашем кабинете.');
      } catch (error) {
        const pending = orderRequests.read(requestScope('order'));
        $('#checkoutRetry').textContent = pending ? 'Ответ пока не получен. Повторите с тем же составом и данными — заказ сохранится один раз.' : error.message;
        toast(error.message);
      }
      finally { state.orderBusy = false; btn.disabled = false; btn.setAttribute('aria-busy', 'false'); btn.textContent = label; }
    });
    $('#spinButton').addEventListener('click',spin);
    $('#wheelSound').addEventListener('change', e => {
      if (state.wheel) e.target.checked = state.wheel.setSound(e.target.checked);
    });
    $('#wheelLight').addEventListener('change', e => { if (state.wheel) state.wheel.light = e.target.checked; });
    $('#shareReferral').addEventListener('click',async()=>{
      if(!state.referral)return;
      const webLink=`${location.origin}/?ref=${encodeURIComponent(state.referral.code)}#referrals`;
      const botName=document.body.dataset.maxBotUsername || '';
      const maxLink=botName?`https://max.ru/${encodeURIComponent(botName)}?startapp=ref_${encodeURIComponent(state.referral.code)}`:webLink;
      const message=`🦞 Приглашаю в клуб РАКОВАРЪ! Используй мой код ${state.referral.code}. После первой покупки от ${money(state.referral.rules.minimum_order_rub)} получишь ${state.referral.rules.friend_tickets} клубных билетов, а мне начислятся ${state.referral.rules.referrer_tickets}. Открой мини-приложение MAX: ${maxLink} Или сайт: ${webLink}`;
      track('referral_shared',{code:state.referral.code});
      try{if(window.WebApp?.shareMaxContent)await window.WebApp.shareMaxContent({text:message,link:maxLink});else if(navigator.share)await navigator.share({title:'Клуб РАКОВАРЪ',text:message,url:maxLink});else{await navigator.clipboard.writeText(message);toast('Приглашение скопировано.');}}catch(e){if(e?.name!=='AbortError')toast('Не удалось поделиться приглашением.');}
    });
    $('#addBundle').addEventListener('click',()=>state.studio?.add());
    $$('[data-copy]').forEach(btn=>btn.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(btn.dataset.copy);toast(`Промокод ${btn.dataset.copy} скопирован`);}catch{ $('#promoCode').value=btn.dataset.copy; openCart();toast('Промокод перенесён в корзину.');}}));
    $$('[data-category-select]').forEach(btn => btn.addEventListener('click', () => { state.category = btn.dataset.categorySelect; state.catalogLimit=24; renderCategories(); renderProducts(); $('#catalog').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' }); }));
    $('#mobileMenu').addEventListener('click', () => { const expanded = $('.main-nav').classList.toggle('open'); $('#mobileMenu').setAttribute('aria-expanded', String(expanded)); });
    $$('.main-nav a').forEach(a=>a.addEventListener('click',()=>$('.main-nav').classList.remove('open')));
  }
  async function initIdentity() {
    const webApp = window.WebApp;
    if (webApp && typeof webApp.initData === 'string' && webApp.initData.length) {
      try {
        const response = await fetch('/api/max/auth', {
          method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({init_data:webApp.initData})
        });
        const auth = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(auth.message || auth.error || `MAX auth ${response.status}`);
        state.guestId = auth.guest_id;
        state.csrf = auth.csrf_token || '';
        state.maxUser = auth.user || null;
        state.maxStartParam = auth.start_param || '';
        return;
      } catch (error) {
        console.warn('MAX initData validation failed; anonymous preview mode is used.', error);
      }
    }
    state.guestId = getGuestId();
  }

  async function bootstrapIdentity() {
    try { return await api(`/api/bootstrap?guest_id=${encodeURIComponent(state.guestId)}`); }
    catch (error) {
      if (state.maxUser || error.status !== 403 || ![error.code, error.message].includes('visitor_identity_unproven')) throw error;
      // A local ID is not proof of identity after its signed session has gone.
      // Start a fresh anonymous profile once; never retry an identity mismatch.
      try { local.removeItem(guestKey); } catch { /* New ID is held in memory. */ }
      state.guestId = getGuestId();
      const data = await api(`/api/bootstrap?guest_id=${encodeURIComponent(state.guestId)}`);
      toast('Начата новая гостевая сессия. Вход через MAX восстановит профиль MAX.');
      return data;
    }
  }

  async function init() {
    loadCart();
    state.wheel = new window.RakovarWheel.Wheel($('#wheel'), $('#wheelStatus'), $('#wheelSectors'));
    bindEvents();
    try {
      await initIdentity();
      const customer=await api('/api/store/profile');state.customer=customer;state.guestId=customer.guest_id;state.csrf=customer.csrf_token;
      const data = await bootstrapIdentity();
      const shop=await api('/api/store/catalog');state.storeRules=shop.settings;data.products=shop.products;state.catalogLimit=shop.settings.catalog_page_size;
      for(const [key,id] of Object.entries({name:'#customerName',phone:'#customerPhone',address:'#customerAddress'})){if(customer.profile[key])$(id).value=customer.profile[key];}
      $('#deliveryRules').textContent=`Доставка ${money(shop.settings.delivery_fee)} · от ${money(shop.settings.delivery_minimum)}. Бесплатно от ${money(shop.settings.free_delivery_from)}. Самовывоз: Комсомольская, 14.`;
      $('#orderPaymentHint').textContent=shop.settings.order_comment;
      renderOffers(await api('/api/store/promotions'));
      state.csrf=data.csrf_token || state.csrf;
      state.guestId = data.visitor?.guest_id || state.guestId;
      if (!state.maxUser) { try { local.setItem(guestKey, state.guestId); } catch { /* Optional browser storage. */ } }
      await attachReferralFromUrl();
      state.products=data.products; applySiteSettings(data.settings); renderCategories(); renderProducts(); renderBuilder(); renderPrizes(data.prizes); renderContests(data.contests); await refreshGame(); await refreshReferral();
      state.wheel.render(data.wheel_sectors); updateSpinButton();
      if (spinRequests.read(requestScope('spin'))) $('#spinRetry').textContent = 'Есть неподтверждённый запрос. Повторите его, чтобы получить уже сохранённый результат.';
      if (orderRequests.read(requestScope('order'))) $('#checkoutRetry').textContent = 'Есть неподтверждённая отправка. Для проверки результата повторите с тем же составом и данными.';
      if ($('#spinHint') && data.loyalty_rules) $('#spinHint').textContent = `Билеты за покупки: 1 билет за каждые ${money(data.loyalty_rules.rub_per_ticket)} подтверждённой оплаты. Дополнительные билеты — за акции и конкурсы по их правилам.`;
      if (state.maxUser) toast(`Вы вошли через MAX, ${state.maxUser.first_name || 'добро пожаловать'}!`);
    } catch (error) {
      $('#products').innerHTML = `<div class="empty-state">Не удалось загрузить витрину: ${esc(error.message)}<p><button class="btn btn-outline" id="storefrontRetry">Повторить загрузку</button></p></div>`;
      $('#storefrontRetry').addEventListener('click', () => location.reload());
      $('#wheelStatus').textContent = 'Колесо недоступно до загрузки призового фонда.';
      updateSpinButton();
    }
    updateCart(); if (state.csrf) track('page_view');
  }
  document.addEventListener('DOMContentLoaded',init);
})();

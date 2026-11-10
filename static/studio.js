(() => {
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=n=>new Intl.NumberFormat('ru-RU').format(n)+' ₽';
  const image=p=>p.image_url||'/static/images/'+(p.image||'opt_hero.svg').split('/').map(encodeURIComponent).join('/');
  function mount(products,helpers){
    const $=s=>document.querySelector(s), selected=new Map(),lookup=new Map(products.map(p=>[p.id,p]));
    let category='all',search='';
    const priority=['crayfish-medium-kg','set-4-morya','shrimp-assorted-fried','mussels-wine','set-firmenny','dorado-grill','live-crayfish-request','edible-bouquet-request'];
    const rank=p=>priority.includes(p.id)?priority.indexOf(p.id):priority.length;
    const available=products.filter(p=>p.stock>0).sort((a,b)=>rank(a)-rank(b));
    $('#studioCategory').innerHTML='<option value="all">Все разделы</option>'+[...new Set(available.map(p=>p.category))].map(c=>`<option>${esc(c)}</option>`).join('');
    function summary(){
      let total=0,unknown=false,count=0;
      const rows=[...selected].map(([id,qty])=>{const p=lookup.get(id);count+=qty;total+=p.price*qty;unknown||=!!p.price_on_request;return `<div class="studio-selection-line"><div><b>${esc(p.title)}</b><small>${qty} × ${p.price_on_request?'по запросу':money(p.price)}</small></div><button type="button" data-remove="${esc(id)}" aria-label="Убрать ${esc(p.title)}">×</button></div>`;});
      $('#builderSelection').innerHTML=rows.join('')||'<p class="studio-empty">Выберите любимые блюда слева. Здесь появится ваш состав.</p>';
      $('#builderTotal').textContent=(unknown?'от ':'')+money(total);
      const guests=Math.max(1,Number($('#studioGuests').value)||1),budget=Number($('#studioBudget').value)||0;
      $('#builderPortions').textContent=count?`${count} порц. · ${guests} гост. · ${money(Math.round(total/guests))} на человека`:'Ваш набор пока пуст';
      $('#builderBudgetNote').textContent=unknown?'Стоимость выбранных позиций по запросу согласуем отдельно.':budget&&total>budget?'Выбранное превышает ваш ориентир бюджета на '+money(total-budget):budget?'В пределах бюджета. Осталось '+money(Math.max(0,budget-total)):'Количество и выход указаны для каждой позиции меню.';
      $('#addBundle').disabled=!count||unknown||selected.size>30;
      const text='Здравствуйте! Хочу согласовать сет РАКОВАРЪ. Повод: '+$('#studioOccasion').value+'. Гостей: '+guests+'. '+[...selected].map(([id,q])=>lookup.get(id).title+' × '+q).join('; ');
      $('#bundleInquiry').href='https://vk.me/rakovar_yar?text='+encodeURIComponent(text);
      $('#bundleInquiry').hidden=!count;
      $('#builderSelection').querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{selected.delete(b.dataset.remove);render();});
    }
    function render(){
      const active=document.activeElement;
      const focusKey=['data-plus','data-minus','data-build'].find(key=>active?.hasAttribute(key));
      const focusId=focusKey?active.getAttribute(focusKey):'';
      const filtered=available.filter(p=>(category==='all'||p.category===category)&&`${p.title} ${p.description}`.toLowerCase().includes(search));
      $('#studioCount').textContent=`${filtered.length} из ${available.length} позиций`;
      $('#builderItems').innerHTML=filtered.map(p=>{const qty=selected.get(p.id)||0;return `<article class="studio-product ${qty?'is-selected':''}"><label class="studio-check"><input type="checkbox" aria-label="Добавить ${esc(p.title)} в набор" data-build="${esc(p.id)}" ${qty?'checked':''}><span>В набор</span></label><img loading="lazy" src="${esc(image(p))}" alt="${esc(p.title)}"><div class="studio-product-copy"><small>${esc(p.category)}${p.weight_label?' · '+esc(p.weight_label):''}</small><h4>${esc(p.title)}</h4><b>${p.price_on_request?'По запросу':money(p.price)}</b><div class="studio-quantity"><button type="button" data-minus="${esc(p.id)}" aria-label="Уменьшить ${esc(p.title)}">−</button><output>${qty}</output><button type="button" data-plus="${esc(p.id)}" aria-label="Увеличить ${esc(p.title)}">+</button></div></div></article>`;}).join('')||'<p class="empty-state">Ничего не найдено. Попробуйте другой раздел или название.</p>';
      $('#builderItems').querySelectorAll('[data-build]').forEach(el=>el.onchange=()=>{if(el.checked)selected.set(el.dataset.build,1);else selected.delete(el.dataset.build);render();});
      $('#builderItems').querySelectorAll('[data-plus],[data-minus]').forEach(el=>el.onclick=()=>{const id=el.dataset.plus||el.dataset.minus;const max=Math.min(50,lookup.get(id).stock);const qty=Math.max(0,Math.min(max,(selected.get(id)||0)+(el.dataset.plus?1:-1)));if(qty)selected.set(id,qty);else selected.delete(id);render();});
      summary();
      if(focusKey)document.querySelector(`[${focusKey}="${CSS.escape(focusId)}"]`)?.focus({preventScroll:true});
    }
    $('#studioSearch').oninput=e=>{search=e.target.value.toLowerCase();render();};
    $('#studioCategory').onchange=e=>{category=e.target.value;render();};
    ['#studioGuests','#studioBudget','#studioOccasion'].forEach(id=>$(id).onchange=summary);
    document.querySelectorAll('[data-studio-preset]').forEach(b=>b.onclick=()=>{selected.clear();const preset=b.dataset.studioPreset;const ids=preset==='two'?['set-for-two-shrimp']:preset==='party'?['crayfish-medium-kg','shrimp-assorted-fried','mussels-wine']:['set-firmenny'];ids.forEach(id=>{if(lookup.has(id))selected.set(id,1);});$('#studioGuests').value=preset==='two'?'2':preset==='party'?'4':'2';render();});
    render();
    return {select(id){if(lookup.has(id)){selected.set(id,Math.min(50,lookup.get(id).stock,(selected.get(id)||0)+1));render();}},add(){const rows=[...selected].map(([id,quantity])=>({id,quantity}));if(!rows.length)return helpers.toast('Выберите блюда для набора.');if(rows.some(r=>lookup.get(r.id).price_on_request))return helpers.toast('Согласуйте стоимость позиций по запросу.');helpers.addBatch(rows);}};
  }
  function mountLive(product){
    const root=document.querySelector('#liveCrayfish');if(!root)return;
    const options=product?.live_size_options||[{name:'Mini',weight:'15–30 г/шт.'},{name:'Standart',weight:'30–50 г/шт.'},{name:'Maxi',weight:'50–70 г/шт.'},{name:'Mega',weight:'70–90 г/шт.'},{name:'XXL',weight:'90–110 г/шт.'}];
    document.querySelector('#liveSizes').innerHTML=options.map((s,i)=>`<label class="live-size"><input type="radio" name="live-size" value="${esc(s.name)}" ${i===1?'checked':''}><span><b>${esc(s.name)}</b><small>${esc(s.weight||s.weight_label||'')}</small></span></label>`).join('');
    function update(){const size=root.querySelector('[name="live-size"]:checked')?.value||'подобрать';const weight=document.querySelector('#liveWeight').value;const method=document.querySelector('#livePreparation').value;const photo=options.find(option=>option.name===size)?.image||product?.image;if(photo)document.querySelector('#livePhoto').src='/static/images/'+photo;document.querySelector('#liveSummary').textContent=`${size} · ${weight} кг · ${method}`;document.querySelector('#liveInquiry').href='https://vk.me/rakovar_yar?text='+encodeURIComponent(`Здравствуйте! Интересуют раки ${size}, ${weight} кг. ${method}. Подскажите наличие, стоимость и время получения.`);}
    root.querySelectorAll('input,select').forEach(el=>{el.onchange=update;el.oninput=update;});update();
  }
  window.RakovarStudio={mount,mountLive,image};
})();

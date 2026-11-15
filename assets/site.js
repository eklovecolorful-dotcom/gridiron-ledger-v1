/* 球場帳本 site script: theme, first-touch source, waitlist mailto, watchlist, service worker.
   No network calls unless you configure events_endpoint in ledger.config.json. */
(function(){
  var store={get:function(k){try{return window.localStorage.getItem(k);}catch(e){return null;}},
             set:function(k,v){try{window.localStorage.setItem(k,v);return true;}catch(e){return false;}},
             del:function(k){try{window.localStorage.removeItem(k);}catch(e){}}};
  var root=document.documentElement, body=document.body;

  // theme toggle
  var saved=store.get('gl-theme'); if(saved==='light'||saved==='dark'){root.setAttribute('data-theme',saved);}
  var tb=document.querySelector('[data-theme-toggle]');
  if(tb){tb.addEventListener('click',function(){
    var cur=root.getAttribute('data-theme')||(window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
    var next=cur==='dark'?'light':'dark'; root.setAttribute('data-theme',next); store.set('gl-theme',next);
    tb.setAttribute('aria-pressed',next==='dark'?'true':'false');});}

  // first-touch source: from landing page data attributes or ?src=&c=
  var qs={}; try{new URLSearchParams(location.search).forEach(function(v,k){qs[k]=v;});}catch(e){}
  var src=body.getAttribute('data-src')||qs.src, c=body.getAttribute('data-c')||qs.c;
  var ok=/^[A-Za-z0-9_-]{1,40}$/;
  if(src&&ok.test(src)&&(!c||ok.test(c))){
    if(!store.get('gl-first')){store.set('gl-first',JSON.stringify({src:src,c:c||'',t:new Date().toISOString().slice(0,10)}));}
    var ep=body.getAttribute('data-endpoint');
    if(ep&&navigator.sendBeacon){try{navigator.sendBeacon(ep,JSON.stringify({date:new Date().toISOString().slice(0,10),src:src,c:c||'',event:'click',amount:0}));}catch(e){}}
  }
  function first(){try{return JSON.parse(store.get('gl-first')||'null');}catch(e){return null;}}

  // waitlist signup: opens the visitor's mail app; nothing is sent by this page
  [].forEach.call(document.querySelectorAll('form[data-signup]'),function(f){
    f.addEventListener('submit',function(ev){
      var input=f.querySelector('input[type=email]'); if(!input||!input.value||!input.checkValidity()){return;}
      ev.preventDefault();
      var ft=first()||{src:'direct',c:''};
      var to=f.getAttribute('data-to');
      var lines=['請把我加入球場帳本的電子報名單。','Email: '+input.value,'來源 src: '+ft.src,'內容 c: '+(ft.c||'-'),'','（這封信由你的郵件程式寄出，寄出後才算完成。）'];
      var url='mailto:'+to+'?subject='+encodeURIComponent('訂閱球場帳本 Gridiron Ledger')+'&body='+encodeURIComponent(lines.join('\n'));
      var st=f.querySelector('[data-status]');
      if(st){st.textContent='已開啟郵件程式，按「寄出」才算完成。沒有反應的話，請直接寄信到 '+to+'。';}
      location.href=url;
    });
  });

  // watchlist card
  var card=document.querySelector('[data-watchlist]');
  if(card){
    var key='gl-watch-'+card.getAttribute('data-watchlist');
    var state={}; try{state=JSON.parse(store.get(key)||'{}')||{};}catch(e){state={};}
    var boxes=card.querySelectorAll('input[type=checkbox]'), prog=card.querySelector('[data-progress]'), warn=card.querySelector('[data-storage-warn]');
    function paint(){var n=0;[].forEach.call(boxes,function(b){if(b.checked){n++;}});if(prog){prog.textContent=n+' / '+boxes.length;}}
    [].forEach.call(boxes,function(b){b.checked=!!state[b.value];
      b.addEventListener('change',function(){state[b.value]=b.checked;
        if(!store.set(key,JSON.stringify(state))&&warn){warn.hidden=false;} paint();});});
    var rs=card.querySelector('[data-reset]');
    if(rs){rs.addEventListener('click',function(){state={};store.del(key);[].forEach.call(boxes,function(b){b.checked=false;});paint();});}
    paint();
  }

  // offline support
  var sw=body.getAttribute('data-sw');
  if(sw&&'serviceWorker' in navigator&&/^https?:$/.test(location.protocol)){
    window.addEventListener('load',function(){navigator.serviceWorker.register(sw).catch(function(){});});
  }
})();

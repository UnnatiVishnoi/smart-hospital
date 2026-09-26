/* MediServe — Premium interactions, animations, charts */
(function(){
  "use strict";

  // ===== Chart.js defaults =====
  if(typeof Chart !== 'undefined'){
    Chart.defaults.font.family = "'Inter', 'Plus Jakarta Sans', sans-serif";
    Chart.defaults.color = '#66748e';
    Chart.defaults.borderColor = '#eef2f7';
    Chart.defaults.plugins.tooltip = {
      backgroundColor: '#0f2040',
      titleColor: '#e0e7ff',
      bodyColor: '#c4cfe6',
      borderColor: 'rgba(255,255,255,.08)',
      borderWidth: 1,
      cornerRadius: 10,
      padding: 12,
      titleFont: { size: 12, weight: '600' },
      bodyFont: { size: 12 },
      displayColors: true,
      boxPadding: 3,
    };
    Chart.defaults.plugins.legend = {
      labels: { boxWidth: 10, padding: 16, usePointStyle: true, pointStyle: 'circle' }
    };
    Chart.defaults.animation = {
      duration: 800,
      easing: 'easeOutQuart',
      delay: function(context){ return context.dataIndex * 60; }
    };
  }

  // ===== Canvas accessibility =====
  document.querySelectorAll('canvas[id]').forEach(function(cv){
    if(!cv.getAttribute('aria-label')){
      cv.setAttribute('role', 'img');
      var label = (cv.id || 'chart').replace(/([A-Z])/g, ' $1').replace(/[-_]/g, ' ').trim();
      cv.setAttribute('aria-label', label + ' chart');
    }
  });

  // ===== Scrollable tables =====
  document.querySelectorAll('.table-wrap').forEach(function(w){
    if(!w.hasAttribute('tabindex')) w.setAttribute('tabindex', '0');
    if(!w.getAttribute('role')) w.setAttribute('role', 'region');
    if(!w.getAttribute('aria-label')) w.setAttribute('aria-label', 'Scrollable table');
  });

  // ===== Active nav a11y =====
  document.querySelectorAll('.side-link.active').forEach(function(a){
    a.setAttribute('aria-current', 'page');
  });

  // ===== Sidebar collapse =====
  var shell = document.getElementById('appShell');
  try{
    if(shell && localStorage.getItem('ms-collapse') === '1' && window.innerWidth >= 992){
      shell.classList.add('collapsed');
    }
  }catch(e){}
  var cBtn = document.getElementById('collapseBtn');
  if(cBtn && shell){
    cBtn.addEventListener('click', function(){
      shell.classList.toggle('collapsed');
      try{ localStorage.setItem('ms-collapse', shell.classList.contains('collapsed') ? '1' : '0'); }catch(e){}
      // Dispatch resize for charts
      window.dispatchEvent(new Event('resize'));
    });
  }

  // ===== Mobile drawer =====
  var mBtn = document.getElementById('mobileBtn');
  var scrim = document.getElementById('scrim');
  function closeMobile(){ if(shell) shell.classList.remove('mobile-open'); }
  if(mBtn && shell){ mBtn.addEventListener('click', function(){ shell.classList.add('mobile-open'); }); }
  if(scrim && shell){
    scrim.addEventListener('click', closeMobile);
    scrim.addEventListener('keydown', function(e){ if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); closeMobile(); } });
  }
  document.querySelectorAll('.side-link').forEach(function(a){ a.addEventListener('click', closeMobile); });

  // ===== Mobile search =====
  var msBtn = document.getElementById('mobileSearchBtn');
  var msWrap = document.getElementById('mobileSearchWrap');
  if(msBtn && msWrap){
    msBtn.addEventListener('click', function(){
      var open = msWrap.classList.toggle('open');
      msBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if(open){ var i = msWrap.querySelector('input'); if(i) i.focus(); }
    });
  }

  // ===== Keyboard shortcuts =====
  document.addEventListener('keydown', function(e){
    if((e.metaKey||e.ctrlKey) && e.key.toLowerCase==='k'){
      e.preventDefault();
      var desk = document.getElementById('globalSearch');
      if(desk && window.innerWidth >= 992){ desk.focus(); }
      else if(msWrap && msBtn){ msWrap.classList.add('open'); msBtn.setAttribute('aria-expanded','true'); }
    }
    if(e.key==='Escape' && shell) shell.classList.remove('mobile-open');
  });

  // ===== Topbar scroll shadow =====
  var topbar = document.querySelector('.topbar');
  if(topbar){
    var checkScroll = function(){
      if(window.scrollY > 0) topbar.classList.add('scrolled');
      else topbar.classList.remove('scrolled');
    };
    window.addEventListener('scroll', checkScroll, { passive: true });
    checkScroll();
  }

  // ===== Page content entrance =====
  var content = document.getElementById('mainContent');
  if(content && !content.classList.contains('page-enter')){
    content.classList.add('page-enter');
  }

  // ===== Toast notifications =====
  window.toast = function(msg, tone){
    tone = tone || '';
    var stack = document.getElementById('toastStack');
    if(!stack) return;
    var el = document.createElement('div');
    el.className = 'app-toast' + (tone ? ' ' + tone : '');
    var icon = tone === 'error' ? 'bi-exclamation-circle-fill' : tone === 'warning' ? 'bi-exclamation-triangle-fill' : 'bi-check-circle-fill';
    el.innerHTML = '<i class="bi ' + icon + '"></i><span>' + msg + '</span><button class="toast-close" aria-label="Close"><i class="bi bi-x"></i></button>';
    el.querySelector('.toast-close').addEventListener('click', function(){
      el.classList.add('removing');
      setTimeout(function(){ el.remove(); }, 300);
    });
    stack.appendChild(el);
    setTimeout(function(){
      if(el.parentNode){ el.classList.add('removing'); setTimeout(function(){ el.remove(); }, 300); }
    }, 3500);
  };

  // ===== Intersection Observer for animations =====
  if('IntersectionObserver' in window){
    var observer = new IntersectionObserver(function(entries){
      entries.forEach(function(entry){
        if(entry.isIntersecting){
          entry.target.style.opacity = '';
          entry.target.style.transform = '';
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -20px 0px' });

    document.querySelectorAll('.panel, .kpi').forEach(function(el){
      el.style.opacity = '0';
      el.style.transform = 'translateY(8px)';
      el.style.transition = 'opacity .5s ease, transform .5s cubic-bezier(.4,0,.2,1)';
      observer.observe(el);
    });
  }

})();

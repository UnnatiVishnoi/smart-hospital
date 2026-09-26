// Chart.js previews — demo data only, labelled as such
(function(){
  if(typeof Chart === 'undefined') return;
  Chart.defaults.font.family = 'Inter, sans-serif';
  Chart.defaults.color = '#66748e';
  const navy = '#0f2040', blue = '#1e63e9', teal = '#0e9f8a', amber = '#c47b12', red = '#c0362c', gray = '#cbd5e8';
  const sc = document.getElementById('statusChart');
  if(sc){ new Chart(sc, {type:'doughnut',
    data:{labels:['Operational','Under maintenance','Breakdown','Standby'], datasets:[{data:[214,18,11,5], backgroundColor:[teal,amber,red,gray], borderWidth:2, borderColor:'#fff'}]},
    options:{maintainAspectRatio:false, cutout:'68%', plugins:{legend:{position:'bottom', labels:{boxWidth:10, padding:14, font:{size:11}}}}}}); }
  const tc = document.getElementById('trendChart');
  if(tc){ new Chart(tc, {type:'bar',
    data:{labels:['Apr','May','Jun','Jul','Aug','Sep'],
      datasets:[
        {label:'Preventive', data:[22,26,24,30,28,34], backgroundColor:blue, borderRadius:5, barPercentage:.55},
        {label:'Corrective', data:[14,11,16,12,9,13], backgroundColor:'#b9cdf3', borderRadius:5, barPercentage:.55}]},
    options:{maintainAspectRatio:false, scales:{x:{grid:{display:false}}, y:{beginAtZero:true, grid:{color:'#eef2f7'}}}, plugins:{legend:{position:'bottom', labels:{boxWidth:10, font:{size:11}}}}}}); }
})();

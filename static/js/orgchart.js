// Org Chart
// ---------------------------------------------------------------------------
async function loadOrgChart() {
  if(currentUser.role==='superadmin'&&!currentInstitution) return;
  const res=await api('/api/org-chart');
  if(!res||!res.ok) return;
  orgData=await res.json();
  const sf=document.getElementById('orgStatusFilter')?.value||'';
  renderOrgChart(sf?orgData.filter(e=>e.status===sf):orgData);
}

function renderOrgChart(nodes) {
  const NODE_W=180,NODE_H=70,GAP_X=30,GAP_Y=60;
  const byId={};nodes.forEach(n=>byId[n.employee_id]=n);
  const children={};const roots=[];
  nodes.forEach(n=>{
    if(!n.reports_to||n.reports_to===n.employee_id||!byId[n.reports_to]) roots.push(n.employee_id);
    else (children[n.reports_to]=children[n.reports_to]||[]).push(n.employee_id);
  });
  if(!roots.length&&nodes.length) roots.push(nodes[0].employee_id);
  const pos={};let maxX=0,maxY=0;
  function layout(id,x,y){
    pos[id]={x,y};if(y>maxY)maxY=y;
    const kids=children[id]||[];
    if(!kids.length){if(x+NODE_W>maxX)maxX=x+NODE_W;return NODE_W;}
    let totalW=0;
    kids.forEach(kid=>{
      const w=layout(kid,x+totalW,y+NODE_H+GAP_Y);
      totalW+=w+GAP_X;
    });
    totalW-=GAP_X;
    const center=x+totalW/2-NODE_W/2;pos[id]={x:center,y};
    if(center+NODE_W>maxX)maxX=center+NODE_W;return totalW;
  }
  let cx=0;roots.forEach(r=>{const w=layout(r,cx,0);cx+=w+GAP_X*2;});
  const svgW=Math.max(maxX+40,400),svgH=maxY+NODE_H+40;
  const svg=document.getElementById('orgSvg');
  svg.setAttribute('viewBox',`0 0 ${svgW} ${svgH}`);
  svg.setAttribute('width',svgW);svg.setAttribute('height',svgH);
  let lines='',boxes='';
  nodes.forEach(n=>{
    const p=pos[n.employee_id];if(!p) return;
    (children[n.employee_id]||[]).forEach(cid=>{
      const cp=pos[cid];if(!cp) return;
      const x1=p.x+NODE_W/2,y1=p.y+NODE_H,x2=cp.x+NODE_W/2,y2=cp.y,my=(y1+y2)/2;
      lines+=`<path d="M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}" fill="none" stroke="#cbd5e1" stroke-width="1.5"/>`;
    });
    const active=n.status==='Active';
    const nm=n.full_name.length>18?n.full_name.slice(0,17)+'…':n.full_name;
    const ds=n.designation.length>22?n.designation.slice(0,21)+'…':n.designation;
    boxes+=`<g onclick="viewEmployee('${n.employee_id}')" style="cursor:pointer">
      <rect x="${p.x}" y="${p.y}" width="${NODE_W}" height="${NODE_H}" rx="10" fill="white" stroke="${active?'#bfdbfe':'#e2e8f0'}" stroke-width="1.5" filter="drop-shadow(0 1px 3px rgba(0,0,0,.07))"/>
      <circle cx="${p.x+14}" cy="${p.y+15}" r="5" fill="${active?'#10b981':'#94a3b8'}"/>
      <text x="${p.x+24}" y="${p.y+20}" font-size="11" fill="#1e293b" font-weight="600" font-family="sans-serif">${esc(nm)}</text>
      <text x="${p.x+10}" y="${p.y+37}" font-size="10" fill="#64748b" font-family="sans-serif">${esc(ds)}</text>
      <text x="${p.x+10}" y="${p.y+52}" font-size="9" fill="#94a3b8" font-family="sans-serif">${esc(n.department)}</text>
    </g>`;
  });
  svg.innerHTML=lines+boxes;
  if(!nodes.length) svg.innerHTML='<text x="50%" y="60" text-anchor="middle" fill="#94a3b8" font-size="14" font-family="sans-serif">No employees to display</text>';
}

// ---------------------------------------------------------------------------

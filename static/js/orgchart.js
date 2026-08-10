// Org Chart
// ---------------------------------------------------------------------------
// Full org data (unfiltered by root/collapse) is kept in orgData; orgRootId
// and orgCollapsed let the user drill into a subtree and fold branches so
// the rendered SVG only ever spans as wide as what's currently expanded,
// instead of the whole company at once. orgView (scale/tx/ty) is a separate
// pan/zoom transform applied on top of that, for the cases where even a
// focused subtree is still wider than the panel.
let orgRootId = null;
let orgCollapsed = new Set();
let orgView = { scale: 1, tx: 0, ty: 0 };
let orgDrag = null;
// 'tree' (SVG boxes-and-lines) or 'list' (plain collapsible nested list,
// compact horizontally — see renderOrgList). orgRootId/orgCollapsed are
// shared between both views, so switching tabs mid-drill-down or
// mid-collapse keeps exactly what you had expanded/focused.
let orgViewMode = 'tree';

async function loadOrgChart() {
  if(currentUser.role==='superadmin'&&!currentInstitution) return;
  const res=await api('/api/org-chart');
  if(!res||!res.ok) return;
  orgData=await res.json();
  orgRootId=null;
  orgCollapsed=orgDefaultCollapsed(orgData);
  orgResetView();
  refreshOrgChart();
}

function orgSwitchView(mode) {
  orgViewMode=mode;
  document.getElementById('orgTab_tree').classList.toggle('view-tab-active', mode==='tree');
  document.getElementById('orgTab_tree').classList.toggle('text-slate-500', mode!=='tree');
  document.getElementById('orgTab_list').classList.toggle('view-tab-active', mode==='list');
  document.getElementById('orgTab_list').classList.toggle('text-slate-500', mode!=='list');
  document.getElementById('orgChartWrap').classList.toggle('hidden', mode!=='tree');
  document.getElementById('orgListWrap').classList.toggle('hidden', mode!=='list');
  document.getElementById('orgZoomControls').classList.toggle('hidden', mode!=='tree');
  document.getElementById('orgTreeHint').classList.toggle('hidden', mode!=='tree');
  document.getElementById('orgListHint').classList.toggle('hidden', mode!=='list');
  refreshOrgChart();
}

// Fresh load with nothing collapsed would render the entire company as one
// flat-wide tree — exactly the "too wide" problem this feature exists to
// fix. Default to showing just the first two generations (top of the org +
// their direct reports) and fold everything deeper, so the initial view is
// always a bounded width; the user expands further branches on demand.
function orgDefaultCollapsed(nodes) {
  const byId={};nodes.forEach(n=>byId[n.employee_id]=n);
  const children={};const roots=[];
  nodes.forEach(n=>{
    if(!n.reports_to||n.reports_to===n.employee_id||!byId[n.reports_to]) roots.push(n.employee_id);
    else (children[n.reports_to]=children[n.reports_to]||[]).push(n.employee_id);
  });
  const collapsed=new Set();
  const DEPTH_LIMIT=2;
  function walk(id,depth){
    const kids=children[id]||[];
    if(depth>=DEPTH_LIMIT&&kids.length){collapsed.add(id);return;}
    kids.forEach(k=>walk(k,depth+1));
  }
  roots.forEach(r=>walk(r,0));
  return collapsed;
}

function refreshOrgChart() {
  const sf=document.getElementById('orgStatusFilter')?.value||'';
  const nodes=sf?orgData.filter(e=>e.status===sf):orgData;
  if(orgViewMode==='list') renderOrgList(nodes); else renderOrgChart(nodes);
}

function orgFocus(id) {
  orgRootId=id;
  orgResetView();
  refreshOrgChart();
}

function orgToggleCollapse(id) {
  if(orgCollapsed.has(id)) orgCollapsed.delete(id); else orgCollapsed.add(id);
  refreshOrgChart();
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

  renderOrgBreadcrumb(byId);

  // If focused on a subtree, that node becomes the sole root for layout —
  // but only if it's still present after the status filter.
  const layoutRoots=(orgRootId&&byId[orgRootId])?[orgRootId]:roots;

  function countDescendants(id){
    const kids=children[id]||[];
    let n=kids.length;
    kids.forEach(k=>n+=countDescendants(k));
    return n;
  }

  const pos={};let maxX=0,maxY=0;
  function layout(id,x,y){
    pos[id]={x,y};if(y>maxY)maxY=y;
    const kids=orgCollapsed.has(id)?[]:(children[id]||[]);
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
  let cx=0;layoutRoots.forEach(r=>{const w=layout(r,cx,0);cx+=w+GAP_X*2;});
  const contentW=Math.max(maxX+40,400),contentH=maxY+NODE_H+40;
  const svg=document.getElementById('orgSvg');
  const wrap=document.getElementById('orgChartWrap');
  const viewW=Math.max(wrap?.clientWidth||contentW,contentW);
  const viewH=Math.max(wrap?.clientHeight||contentH,contentH,300);
  svg.setAttribute('viewBox',`0 0 ${viewW} ${viewH}`);
  svg.setAttribute('width','100%');svg.setAttribute('height',Math.min(viewH,600));

  let lines='',boxes='';
  const visited=new Set();
  layoutRoots.forEach(r=>walk(r));
  function walk(id){
    if(visited.has(id)) return; visited.add(id);
    const n=byId[id];const p=pos[id];if(!n||!p) return;
    const kids=orgCollapsed.has(id)?[]:(children[id]||[]);
    kids.forEach(cid=>{
      const cp=pos[cid];if(!cp) return;
      const x1=p.x+NODE_W/2,y1=p.y+NODE_H,x2=cp.x+NODE_W/2,y2=cp.y,my=(y1+y2)/2;
      lines+=`<path d="M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}" fill="none" stroke="#cbd5e1" stroke-width="1.5"/>`;
      walk(cid);
    });
    const active=n.status==='Active';
    const nm=n.full_name.length>18?n.full_name.slice(0,17)+'…':n.full_name;
    const ds=n.designation.length>22?n.designation.slice(0,21)+'…':n.designation;
    const hasKids=(children[id]||[]).length>0;
    const collapsed=orgCollapsed.has(id);
    const badge=hasKids?`<g onclick="event.stopPropagation();orgToggleCollapse('${id}')" style="cursor:pointer">
        <circle cx="${p.x+NODE_W/2}" cy="${p.y+NODE_H}" r="9" fill="${collapsed?'#4f46e5':'#fff'}" stroke="#94a3b8" stroke-width="1.5"/>
        <text x="${p.x+NODE_W/2}" y="${p.y+NODE_H+4}" text-anchor="middle" font-size="12" font-weight="700" fill="${collapsed?'#fff':'#64748b'}" font-family="sans-serif">${collapsed?'+':'−'}</text>
      </g>${collapsed?`<text x="${p.x+NODE_W/2}" y="${p.y+NODE_H+22}" text-anchor="middle" font-size="9" fill="#94a3b8" font-family="sans-serif">${countDescendants(id)} hidden</text>`:''}`:'';
    boxes+=`<g style="cursor:pointer">
      <g onclick="orgFocus('${id}')">
        <rect x="${p.x}" y="${p.y}" width="${NODE_W}" height="${NODE_H}" rx="10" fill="white" stroke="${active?'#bfdbfe':'#e2e8f0'}" stroke-width="1.5" filter="drop-shadow(0 1px 3px rgba(0,0,0,.07))"/>
        <circle cx="${p.x+14}" cy="${p.y+15}" r="5" fill="${active?'#10b981':'#94a3b8'}"/>
        <text x="${p.x+24}" y="${p.y+20}" font-size="11" fill="#1e293b" font-weight="600" font-family="sans-serif">${esc(nm)}</text>
        <text x="${p.x+10}" y="${p.y+37}" font-size="10" fill="#64748b" font-family="sans-serif">${esc(ds)}</text>
        <text x="${p.x+10}" y="${p.y+52}" font-size="9" fill="#94a3b8" font-family="sans-serif">${esc(n.department)}</text>
      </g>
      <g onclick="event.stopPropagation();viewEmployee('${id}')" title="View profile">
        <rect x="${p.x+NODE_W-22}" y="${p.y+4}" width="18" height="18" rx="4" fill="transparent"/>
        <path d="M${p.x+NODE_W-18},${p.y+13} a4,4 0 1 0 8,0 a4,4 0 1 0 -8,0 M${p.x+NODE_W-19},${p.y+20} q5,-6 10,0" fill="none" stroke="#94a3b8" stroke-width="1.3"/>
      </g>
      ${badge}
    </g>`;
  }
  svg.innerHTML=`<g id="orgViewport">${lines}${boxes}</g>`;
  if(!nodes.length) svg.innerHTML='<text x="50%" y="60" text-anchor="middle" fill="#94a3b8" font-size="14" font-family="sans-serif">No employees to display</text>';
  applyOrgView();
  wireOrgPanZoom();
}

// Plain collapsible nested list — the "compact horizontally" alternative to
// the SVG tree above. Width only grows with reporting depth (indentation),
// not headcount, since siblings stack vertically instead of spreading out
// in a row; height grows with headcount instead, which scrolls naturally.
// Shares orgCollapsed/orgRootId/orgFocus/orgToggleCollapse with the tree
// view, so collapse state and department-focus carry over when switching tabs.
function renderOrgList(nodes) {
  const byId={};nodes.forEach(n=>byId[n.employee_id]=n);
  const children={};const roots=[];
  nodes.forEach(n=>{
    if(!n.reports_to||n.reports_to===n.employee_id||!byId[n.reports_to]) roots.push(n.employee_id);
    else (children[n.reports_to]=children[n.reports_to]||[]).push(n.employee_id);
  });
  if(!roots.length&&nodes.length) roots.push(nodes[0].employee_id);

  renderOrgBreadcrumb(byId);

  const layoutRoots=(orgRootId&&byId[orgRootId])?[orgRootId]:roots;

  function countDescendants(id){
    const kids=children[id]||[];
    let n=kids.length;
    kids.forEach(k=>n+=countDescendants(k));
    return n;
  }

  const visited=new Set();
  function renderNode(id){
    if(visited.has(id)) return '';
    visited.add(id);
    const n=byId[id];if(!n) return '';
    const kids=children[id]||[];
    const hasKids=kids.length>0;
    const collapsed=orgCollapsed.has(id);
    const active=n.status==='Active';
    const toggle=hasKids
      ?`<button onclick="event.stopPropagation();orgToggleCollapse('${id}')" class="w-5 h-5 flex-shrink-0 flex items-center justify-center text-slate-400 hover:text-slate-700 rounded hover:bg-slate-100" title="${collapsed?'Expand':'Collapse'}">
          <svg class="w-3.5 h-3.5 transition-transform ${collapsed?'':'rotate-90'}" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.21 5.23a.75.75 0 011.06.02l4.5 4.75a.75.75 0 010 1.04l-4.5 4.75a.75.75 0 11-1.08-1.04L11.168 10 7.23 5.79a.75.75 0 01-.02-1.06z" clip-rule="evenodd"/></svg>
        </button>`
      :`<span class="w-5 h-5 flex-shrink-0"></span>`;
    const childCount=hasKids?`<span class="text-[10px] text-slate-400 flex-shrink-0">${collapsed?countDescendants(id)+' hidden':kids.length}</span>`:'';
    const row=`<div class="flex items-center gap-1.5 py-1.5 px-2 rounded-lg hover:bg-slate-50 group">
        ${toggle}
        <span class="w-2 h-2 rounded-full flex-shrink-0 ${active?'bg-emerald-500':'bg-slate-300'}"></span>
        <button onclick="orgFocus('${id}')" class="text-sm font-medium text-slate-800 hover:text-blue-600 truncate text-left flex-shrink-0 max-w-[220px]">${esc(n.full_name)}</button>
        <span class="text-xs text-slate-400 truncate">${esc(n.designation)}</span>
        <span class="text-[10px] text-slate-400 truncate ml-auto flex-shrink-0 hidden sm:inline">${esc(n.department)}</span>
        ${childCount}
        <button onclick="event.stopPropagation();viewEmployee('${id}')" class="opacity-0 group-hover:opacity-100 flex-shrink-0 text-slate-400 hover:text-slate-700" title="View profile">
          <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd"/></svg>
        </button>
      </div>`;
    const childrenHtml=(hasKids&&!collapsed)
      ?`<div class="ml-[9px] border-l border-slate-200 pl-2">${kids.map(renderNode).join('')}</div>`
      :'';
    return `<div>${row}${childrenHtml}</div>`;
  }

  const listEl=document.getElementById('orgListWrap');
  if(!listEl) return;
  const html=layoutRoots.map(renderNode).join('');
  listEl.innerHTML=html||'<p class="text-sm text-slate-400 p-4">No employees to display</p>';
}

function renderOrgBreadcrumb(byId) {
  const el=document.getElementById('orgBreadcrumb');
  if(!el) return;
  if(!orgRootId||!byId[orgRootId]){el.innerHTML='';return;}
  const chain=[];
  let cur=orgRootId;
  let guard=0;
  while(cur&&byId[cur]&&guard++<50){
    chain.unshift(byId[cur]);
    const next=byId[cur].reports_to;
    cur=(next&&next!==cur&&byId[next])?next:null;
  }
  el.innerHTML=`<button onclick="orgFocus(null)" class="text-blue-600 hover:underline flex-shrink-0">All Employees</button>`+
    chain.map(n=>`<span class="flex-shrink-0">&rsaquo;</span><button onclick="orgFocus('${n.employee_id}')" class="hover:underline flex-shrink-0 ${n.employee_id===orgRootId?'font-semibold text-slate-700':'text-blue-600'}">${esc(n.full_name)}</button>`).join('');
}

// ---------------------------------------------------------------------------
// Pan / zoom — a plain transform on a <g> wrapper, driven by drag and wheel.
// Re-wired on every render since renderOrgChart() replaces svg.innerHTML.
// ---------------------------------------------------------------------------
function applyOrgView() {
  const vp=document.getElementById('orgViewport');
  if(vp) vp.setAttribute('transform',`translate(${orgView.tx},${orgView.ty}) scale(${orgView.scale})`);
}

function orgZoomBy(factor, cx, cy) {
  const svg=document.getElementById('orgSvg');
  if(!svg) return;
  const rect=svg.getBoundingClientRect();
  const px=cx!==undefined?cx-rect.left:rect.width/2;
  const py=cy!==undefined?cy-rect.top:rect.height/2;
  const newScale=Math.min(2.5,Math.max(0.25,orgView.scale*factor));
  const ratio=newScale/orgView.scale;
  orgView.tx=px-(px-orgView.tx)*ratio;
  orgView.ty=py-(py-orgView.ty)*ratio;
  orgView.scale=newScale;
  applyOrgView();
}

function orgResetView() {
  orgView={scale:1,tx:0,ty:0};
  applyOrgView();
}

function wireOrgPanZoom() {
  const wrap=document.getElementById('orgChartWrap');
  const svg=document.getElementById('orgSvg');
  if(!wrap||!svg) return;
  if(wrap.dataset.orgPanBound) return;
  wrap.dataset.orgPanBound='1';
  // Pointer capture is only grabbed once real movement is detected (not on
  // every pointerdown) — capturing immediately intercepts the click event a
  // plain tap/click on a node or badge would otherwise deliver, since the
  // browser routes the synthesized click to the capturing element instead
  // of whatever was actually under the cursor.
  wrap.addEventListener('pointerdown',e=>{
    orgDrag={x:e.clientX,y:e.clientY,tx:orgView.tx,ty:orgView.ty,pointerId:e.pointerId,moved:false};
  });
  wrap.addEventListener('pointermove',e=>{
    if(!orgDrag) return;
    const dx=e.clientX-orgDrag.x, dy=e.clientY-orgDrag.y;
    if(!orgDrag.moved){
      if(Math.abs(dx)<4&&Math.abs(dy)<4) return;
      orgDrag.moved=true;
      wrap.style.cursor='grabbing';
      wrap.setPointerCapture(orgDrag.pointerId);
    }
    orgView.tx=orgDrag.tx+dx;
    orgView.ty=orgDrag.ty+dy;
    applyOrgView();
  });
  const endDrag=()=>{orgDrag=null;wrap.style.cursor='grab';};
  wrap.addEventListener('pointerup',endDrag);
  wrap.addEventListener('pointerleave',endDrag);
  wrap.addEventListener('wheel',e=>{
    e.preventDefault();
    orgZoomBy(e.deltaY<0?1.1:0.9, e.clientX, e.clientY);
  },{passive:false});
  wrap.addEventListener('dblclick',()=>orgResetView());
}

// ---------------------------------------------------------------------------

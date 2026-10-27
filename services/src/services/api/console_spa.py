# -*- coding: utf-8 -*-
"""B 端控制台 SPA（自包含单文件：无构建步骤、无 CDN 依赖、局域网可用）。

页面：概览 / 租户管理 / 指标注册中心 / 模型路由 / Capability权限矩阵 /
Memory管理 / 审批中心 / 任务中心 / 发布与灰度 / API测试
认证：JWT（登录后 localStorage），401 自动回登录页。设计：深色侧栏+浅色内容+青色主色。
"""

SPA = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DataAgent 控制台 · 企业级多租户零售经营分析与决策</title>
<style>
:root{--p:#0e7490;--pd:#0a5568;--acc:#06b6d4;--bg:#f1f5f9;--ink:#0f172a;--mut:#64748b;
--side:#0f172a;--side2:#1e293b;--ok:#059669;--err:#dc2626;--warn:#d97706;--line:#e2e8f0}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei","Segoe UI",sans-serif;background:var(--bg);color:var(--ink);font-size:14px}
a{color:var(--acc);text-decoration:none}
/* 登录 */
#login{position:fixed;inset:0;background:linear-gradient(135deg,#0f172a,#0a5568);display:flex;align-items:center;justify-content:center}
#login .card{background:#fff;border-radius:14px;padding:34px 38px;width:380px;box-shadow:0 20px 60px rgba(0,0,0,.4)}
#login h1{font-size:19px;margin-bottom:4px}#login p{color:var(--mut);font-size:12px;margin-bottom:18px}
.fld{margin-bottom:12px}.fld label{font-size:12px;color:var(--mut);display:block;margin-bottom:4px}
.fld input,.fld select{width:100%;padding:9px 11px;border:1px solid #cbd5e1;border-radius:8px;font-size:13px}
.btn{background:var(--p);color:#fff;border:0;border-radius:8px;padding:9px 16px;font-size:13px;cursor:pointer}
.btn:hover{background:var(--pd)}.btn.full{width:100%}.btn.ghost{background:#fff;color:var(--p);border:1px solid var(--p)}
.btn.sm{padding:4px 10px;font-size:12px;border-radius:6px}
.btn.danger{background:#fee2e2;color:var(--err);border:1px solid #fecaca}
.btn.ok{background:#d1fae5;color:var(--ok);border:1px solid #a7f3d0}
.err{color:var(--err);font-size:12px;min-height:16px;margin-top:6px}
/* 布局 */
#app{display:none}
aside{position:fixed;left:0;top:0;bottom:0;width:212px;background:var(--side);color:#cbd5e1;overflow-y:auto}
.brand{padding:18px 18px 14px;border-bottom:1px solid var(--side2)}
.brand b{color:#fff;font-size:16px}.brand span{display:block;font-size:11px;color:#64748b;margin-top:2px}
nav{padding:10px 0}
nav a{display:flex;align-items:center;gap:10px;padding:10px 18px;color:#94a3b8;font-size:13px;border-left:3px solid transparent}
nav a:hover{color:#e2e8f0;background:var(--side2)}
nav a.on{color:#fff;background:var(--side2);border-left-color:var(--acc)}
nav .sec{padding:14px 18px 4px;font-size:11px;color:#475569;letter-spacing:1px}
main{margin-left:212px;padding:0 22px 40px}
header{display:flex;justify-content:space-between;align-items:center;padding:16px 0 12px;border-bottom:1px solid var(--line);margin-bottom:18px;background:var(--bg)}
header h2{font-size:17px}
.uinfo{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--mut)}
.avatar{width:30px;height:30px;border-radius:50%;background:var(--acc);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600}
/* 组件 */
.grid{display:grid;gap:14px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px}
.kpi .v{font-size:26px;font-weight:700;color:var(--pd)}.kpi .l{font-size:12px;color:var(--mut);margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:9px 10px;color:var(--mut);font-weight:500;font-size:12px;border-bottom:1px solid var(--line);background:#f8fafc}
td{padding:9px 10px;border-bottom:1px solid #f1f5f9}
tr:hover td{background:#f8fafc}
.tag{display:inline-block;padding:2px 9px;border-radius:10px;font-size:11px}
.t-ok{background:#d1fae5;color:var(--ok)}.t-err{background:#fee2e2;color:var(--err)}
.t-warn{background:#fef3c7;color:var(--warn)}.t-info{background:#cffafe;color:#0e7490}
.t-mut{background:#f1f5f9;color:var(--mut)}
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:10px;flex-wrap:wrap}
.toolbar .search{display:flex;gap:8px;flex:1;max-width:340px}
.toolbar input{flex:1;padding:7px 10px;border:1px solid #cbd5e1;border-radius:8px}
/* 弹窗 */
mask{position:fixed;inset:0;background:rgba(15,23,42,.5);display:none;align-items:center;justify-content:center;z-index:50}
mask.show{display:flex}
.modal{background:#fff;border-radius:12px;padding:22px;width:460px;max-height:84vh;overflow:auto}
.modal h3{font-size:15px;margin-bottom:14px}
.modal .row2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
pre{background:#0f172a;color:#abb2bf;padding:12px;border-radius:8px;font-size:12px;overflow:auto;font-family:Consolas,monospace}
.hint{font-size:12px;color:var(--mut);line-height:1.7}
.toast{position:fixed;right:18px;top:18px;z-index:99;padding:11px 16px;border-radius:9px;color:#fff;font-size:13px;box-shadow:0 8px 22px rgba(0,0,0,.25);display:none}
.empty{padding:30px;text-align:center;color:var(--mut);font-size:13px}
.mono{font-family:Consolas,monospace;font-size:12px}
</style></head><body>
<div id="login"><div class="card">
<h1>DataAgent 企业控制台</h1><p>多租户零售经营分析 · Auth/Tenant/RBAC/Quota</p>
<div class="fld"><label>用户名</label><input id="lu" value="admin"></div>
<div class="fld"><label>密码</label><input id="lp" type="password" value="admin123"></div>
<div class="err" id="lerr"></div>
<button class="btn full" onclick="doLogin()">登 录</button>
<p class="hint" style="margin-top:14px">演示账号：admin/admin123 · approver/approve123 · analyst/analyst123</p>
</div></div>
<div id="app">
<aside><div class="brand"><b>DataAgent</b><span>企业级 Agent 工程架构</span></div>
<nav id="nav">
<div class="sec">运营</div>
<a data-p="dash" class="on">📊 概览</a>
<a data-p="tasks">🗂️ 任务中心</a>
<a data-p="approvals">✅ 审批中心</a>
<div class="sec">治理</div>
<a data-p="tenants">🏢 租户管理</a>
<a data-p="metrics">📐 指标注册中心</a>
<a data-p="routing">🔀 模型路由</a>
<a data-p="cap">🧩 Capability 权限</a>
<a data-p="memory">💾 Memory 管理</a>
<a data-p="release">🚀 发布与灰度</a>
<div class="sec">开发</div>
<a data-p="api">🧪 API 测试</a>
</nav></aside>
<main>
<header><h2 id="ptitle">概览</h2>
<div class="uinfo"><span id="urole" class="tag t-info">admin</span><span id="uname">admin</span>
<div class="avatar" id="uav">A</div><button class="btn ghost sm" onclick="logout()">退出</button></div></header>
<div id="page"></div>
</main></div>
<mask id="mask"><div class="modal" id="modal"></div></mask>
<div class="toast" id="toast"></div>
<script>
const API='';
let USER=null,TOKEN=localStorage.getItem('da_token');
const PAGES={dash:'概览',tasks:'任务中心',approvals:'审批中心',tenants:'租户管理',metrics:'指标注册中心',routing:'模型路由',cap:'Capability 权限矩阵',memory:'Memory 管理',release:'发布与灰度',api:'API 测试'};
/* ---------- 基础 ---------- */
function toast(m,ok=true){const t=document.getElementById('toast');t.textContent=m;t.style.background=ok?'#059669':'#dc2626';t.style.display='block';setTimeout(()=>t.style.display='none',2600)}
async function api(path,opt={}){opt.headers={'Content-Type':'application/json','Authorization':'Bearer '+TOKEN,...(opt.headers||{})};
 try{const r=await fetch(API+path,opt);if(r.status===401){logout();throw new Error('未认证')}const j=await r.text();
  if(!r.ok){let d=j;try{d=JSON.parse(j).detail||j}catch(e){}throw new Error(d)}return JSON.parse(j)}catch(e){if(e.message==='未认证')throw e;toast(e.message.slice(0,80),false);throw e}}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function tag(v,map){const cls=map[v]||'t-mut';return `<span class="tag ${cls}">${esc(v)}</span>`}
function modal(html){document.getElementById('modal').innerHTML=html;document.getElementById('mask').classList.add('show')}
function closeModal(){document.getElementById('mask').classList.remove('show')}
document.getElementById('mask').addEventListener('click',e=>{if(e.target.id==='mask')closeModal()});
/* ---------- 认证 ---------- */
async function doLogin(){const u=lu.value.trim(),p=lp.value;
 try{const r=await fetch(API+'/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
 const j=await r.json();if(!r.ok)throw new Error(j.detail||'登录失败');
 TOKEN=j.token;USER=j.user;localStorage.setItem('da_token',TOKEN);localStorage.setItem('da_role',j.user.role);enter()}catch(e){lerr.textContent=e.message}}
function logout(){TOKEN='';USER=null;localStorage.removeItem('da_token');app.style.display='none';login.style.display='flex'}
function enter(){const payload=JSON.parse(atob(TOKEN.split('.')[1]));USER={username:payload.sub,role:localStorage.getItem('da_role')||'viewer'};
 uname.textContent=payload.sub;urole.textContent=payload.role;uav.textContent=payload.sub[0].toUpperCase();
 app.style.display='block';login.style.display='none';go('dash')}
/* ---------- 路由 ---------- */
document.getElementById('nav').addEventListener('click',e=>{const a=e.target.closest('a');if(a)go(a.dataset.p)});
function go(p){document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('on',a.dataset.p===p));
 ptitle.textContent=PAGES[p];RENDER[p]&&RENDER[p]()}
/* ---------- 页面渲染 ---------- */
const RENDER={};
RENDER.dash=async()=>{const d=await api('/v1/admin/dashboard');
 page.innerHTML=`<div class="grid kpis">
 ${[['任务总数',d.tasks_total??0],['执行成功',d.tasks_succeeded??0],['待审批任务',d.tasks_waiting??0],['待审批单',d.approvals_pending??0],['租户数',d.tenants??0],['注册指标',d.metrics??0]]
 .map(k=>`<div class="card kpi"><div class="v">${k[1]}</div><div class="l">${k[0]}</div></div>`).join('')}</div>
 <div class="grid" style="grid-template-columns:2fr 1fr;margin-top:14px">
 <div class="card"><b style="font-size:13px">区域 GMV Top3（≥1亿行聚合）</b>
 <table style="margin-top:8px"><tr><th>区域</th><th>订单数</th><th>GMV</th></tr>
 ${(d.top_regions||[]).map(r=>`<tr><td>${esc(r.region)}</td><td>${(r.orders||0).toLocaleString()}</td><td class="mono">¥${(r.gmv||0).toLocaleString()}</td></tr>`).join('')||'<tr><td colspan=3 class="empty">暂无（汇总表未就绪）</td></tr>'}</table></div>
 <div class="card"><b style="font-size:13px">快速开始</b><div class="hint" style="margin-top:8px">
 1️⃣ 任务中心 → 提交异析<br>2️⃣ 审批中心 → 批准/拒绝<br>3️⃣ 任务中心 → 查看终态<br>4️⃣ API 测试 → 全接口回归</div></div></div>`};
/* 任务中心 */
RENDER.tasks=async()=>{const ts=await api('/v1/admin/tasks?limit=50');
 page.innerHTML=`<div class="card"><div class="toolbar"><b style="font-size:13px">异步任务（真实队列消费落库）</b>
 <div style="display:flex;gap:8px"><button class="btn sm" onclick="submitTask()">＋ 提交分析任务</button>
 <button class="btn ghost sm" onclick="go('tasks')">刷新</button></div></div>
 <table><tr><th>task_id</th><th>问题</th><th>租户</th><th>状态</th><th>run_id</th><th>审批单</th><th>更新</th></tr>
 ${ts.map(t=>`<tr><td class="mono">${esc((t.task_id||'').slice(0,14))}…</td><td>${esc((t.query||'').slice(0,18))}</td>
 <td>${esc(t.tenant_id)}</td><td>${tag(t.status,{succeeded:'t-ok',failed:'t-err',waiting_approval:'t-warn',running:'t-info',queued:'t-info',canceled:'t-mut'})}</td>
 <td class="mono">${esc((t.run_id||'—').slice(0,12))}</td>
 <td>${t.approval_id?`<a onclick="viewApproval('${t.approval_id}')">${esc(t.approval_id.slice(0,10))}…</a>`:'—'}</td>
 <td class="mono">${esc(String(t.updated_at||'').slice(0,19))}</td></tr>`).join('')||'<tr><td colspan=7 class="empty">暂无任务</td></tr>'}</table></div>`};
async function submitTask(){modal(`<h3>提交经营分析（异步）</h3>
 <div class="fld"><label>分析问题</label><input id="nq" value="华东区本月 GMV 下滑原因诊断"></div>
 <div class="row2"><div class="fld"><label>租户</label><select id="nt">${['ten_a','ten_b','ten_1','ten_2'].map(t=>`<option>${t}</option>`).join('')}</select></div>
 <div class="fld"><label>用户</label><input id="nu" value="u1"></div></div>
 <div style="display:flex;gap:8px;margin-top:8px"><button class="btn" onclick="doSubmit()">提交</button>
 <button class="btn ghost" onclick="closeModal()">取消</button></div>
 <p class="hint" style="margin-top:10px">manual 审批模式下任务将在预算调整处中断，待审批人批准后完成。</p>`)}
async function doSubmit(){try{const j=await api('/v1/analysis',{method:'POST',body:JSON.stringify({query:nq.value,tenant_id:nt.value,user_id:nu.value,async_:true})});
 toast('已入队 task_id='+j.task_id);closeModal();setTimeout(()=>go('tasks'),400)}catch(e){}}
/* 审批中心 */
RENDER.approvals=async()=>{const ap=await api('/v1/admin/approvals?status=pending');
 const done=await api('/v1/admin/approvals?status=approved');
 const rej=await api('/v1/admin/approvals?status=rejected');
 const row=a=>`<tr><td class="mono">${esc(a.approval_id.slice(0,12))}…</td><td>${tag(a.risk_level,{high:'t-err',medium:'t-warn',low:'t-info'})}</td>
 <td>${esc(a.action)}</td><td>${esc(JSON.stringify(a.params||{}).slice(0,26))}…</td><td>${esc(a.requested_by||'')}</td>
 <td class="mono">${esc(String(a.created_at||'').slice(0,19))}</td>
 <td>${a.status==='pending'?`<button class="btn ok sm" onclick="decide('${a.approval_id}','approved')">批准</button>
 <button class="btn danger sm" onclick="decide('${a.approval_id}','rejected')">拒绝</button>
 <button class="btn ghost sm" onclick="viewApproval('${a.approval_id}')">详情</button>`:tag(a.status,{approved:'t-ok',rejected:'t-err'})+` <span class="mono">${esc(a.decided_by||'')}</span>`}</td></tr>`;
 page.innerHTML=`<div class="card"><div class="toolbar"><b style="font-size:13px">待审批（真实 HITL：批准后任务自动恢复）</b>
 <button class="btn ghost sm" onclick="go('approvals')">刷新</button></div>
 <table><tr><th>审批单</th><th>风险</th><th>动作</th><th>参数</th><th>发起</th><th>时间</th><th>操作</th></tr>
 ${ap.map(row).join('')||'<tr><td colspan=7 class="empty">无待审批</td></tr>'}</table>
 <b style="font-size:13px;display:block;margin:16px 0 8px">已决议</b>
 <table><tr><th>审批单</th><th>风险</th><th>动作</th><th>参数</th><th>发起</th><th>时间</th><th>结果</th></tr>
 ${[...done,...rej].map(row).join('')||'<tr><td colspan=7 class="empty">无记录</td></tr>'}</table></div>`};
async function decide(id,d){try{const j=await api(`/v1/admin/approvals/${id}/resolve`,{method:'POST',body:JSON.stringify({decision:d})});
 toast(`已${d==='approved'?'批准':'拒绝'} · 任务→${j.task_status}`);go('approvals')}catch(e){}}
async function viewApproval(id){const a=await api(`/v1/admin/approvals/${id}`);
 modal(`<h3>审批单 ${esc(a.approval_id)}</h3><table>
 ${['action','risk_level','status','requested_by','decided_by','run_id','task_id'].map(k=>`<tr><th>${k}</th><td>${esc(a[k])}</td></tr>`).join('')}</table>
 <b style="font-size:12px;display:block;margin:12px 0 6px">完整动作上下文（防 UI 截断攻击）</b>
 <pre>${esc(JSON.stringify(a.params,null,2))}</pre>
 ${a.status==='pending'?`<div style="display:flex;gap:8px;margin-top:12px">
 <button class="btn ok sm" onclick="closeModal();decide('${a.approval_id}','approved')">批准</button>
 <button class="btn danger sm" onclick="closeModal();decide('${a.approval_id}','rejected')">拒绝</button></div>`
 :'<button class="btn ghost sm" style="margin-top:12px" onclick="closeModal()">关闭</button>'}`)}
/* 租户管理 */
RENDER.tenants=async()=>{const ts=await api('/v1/admin/tenants');
 page.innerHTML=`<div class="card"><div class="toolbar"><b style="font-size:13px">租户（Tenant/Quota/行列权限）</b>
 <button class="btn sm" onclick="editTenant()">＋ 新建租户</button></div>
 <table><tr><th>tenant_id</th><th>名称</th><th>套餐</th><th>角色</th><th>行过滤</th><th>配额RPS</th><th>状态</th><th></th></tr>
 ${ts.map(t=>`<tr><td class="mono">${esc(t.tenant_id)}</td><td>${esc(t.name)}</td><td>${tag(t.plan,{standard:'t-info',pro:'t-ok',free:'t-mut'})}</td>
 <td class="mono">${esc(t.roles)}</td><td>${esc(t.row_filter||'—')}</td><td>${t.quota_rps}</td>
 <td>${tag(t.status,{active:'t-ok',suspended:'t-err'})}</td>
 <td><button class="btn ghost sm" onclick='editTenant(${JSON.stringify(t).replace(/'/g,"&#39;")})'>编辑</button></td></tr>`).join('')}</table></div>`};
function editTenant(t){t=t||{tenant_id:'',name:'',plan:'standard',roles:'analyst',row_filter:'',col_filter:'',quota_rps:60,status:'active'};
 modal(`<h3>${t.tenant_id?'编辑':'新建'}租户</h3>
 <div class="row2"><div class="fld"><label>tenant_id</label><input id="etid" value="${esc(t.tenant_id)}" ${t.tenant_id?'disabled':''}></div>
 <div class="fld"><label>名称</label><input id="etname" value="${esc(t.name)}"></div></div>
 <div class="row2"><div class="fld"><label>套餐</label><select id="etplan">${['free','standard','pro'].map(p=>`<option ${t.plan===p?'selected':''}>${p}</option>`).join('')}</select></div>
 <div class="fld"><label>角色（逗号分隔）</label><input id="etroles" value="${esc(t.roles)}"></div></div>
 <div class="row2"><div class="fld"><label>行过滤（如 region=华东）</label><input id="etrow" value="${esc(t.row_filter||'')}"></div>
 <div class="fld"><label>配额 RPS</label><input id="etq" type="number" value="${t.quota_rps}"></div></div>
 <div class="fld"><label>状态</label><select id="etst"><option value="active" ${t.status==='active'?'selected':''}>active</option><option value="suspended" ${t.status==='suspended'?'selected':''}>suspended</option></select></div>
 <div style="display:flex;gap:8px"><button class="btn" onclick="saveTenant()">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>`)}
async function saveTenant(){try{await api('/v1/admin/tenants',{method:'POST',body:JSON.stringify({
 tenant_id:etid.value,name:etname.value,plan:etplan.value,roles:etroles.value,row_filter:etrow.value||null,quota_rps:+etq.value,status:etst.value})});
 toast('已保存');closeModal();go('tenants')}catch(e){}}
/* 指标注册中心 */
RENDER.metrics=async()=>{const ms=await api('/v1/admin/metrics');
 page.innerHTML=`<div class="card"><div class="toolbar"><b style="font-size:13px">指标注册中心（口径权威定义）</b>
 <button class="btn sm" onclick="editMetric()">＋ 注册指标</button></div>
 <table><tr><th>name</th><th>显示名</th><th>口径公式</th><th>别名</th><th>维度</th><th>版本</th><th>状态</th><th></th></tr>
 ${ms.map(m=>`<tr><td class="mono">${esc(m.name)}</td><td>${esc(m.display_name)}</td><td>${esc((m.formula||'').slice(0,24))}</td>
 <td class="mono">${esc(m.aliases)}</td><td>${esc(m.dimension)}</td><td>v${m.version}</td>
 <td>${tag(m.status,{active:'t-ok',deprecated:'t-mut'})}</td>
 <td><button class="btn ghost sm" onclick='editMetric(${JSON.stringify(m).replace(/'/g,"&#39;")})'>编辑</button></td></tr>`).join('')}</table></div>`};
function editMetric(m){m=m||{name:'',display_name:'',formula:'',aliases:'',dimension:'amount',status:'active'};
 modal(`<h3>${m.name?'编辑':'注册'}指标</h3>
 <div class="row2"><div class="fld"><label>name</label><input id="emn" value="${esc(m.name)}" ${m.name?'disabled':''}></div>
 <div class="fld"><label>显示名</label><input id="emdn" value="${esc(m.display_name)}"></div></div>
 <div class="fld"><label>口径公式（权威定义）</label><input id="emf" value="${esc(m.formula)}"></div>
 <div class="row2"><div class="fld"><label>别名（逗号分隔）</label><input id="ema" value="${esc(m.aliases)}"></div>
 <div class="fld"><label>维度</label><select id="emd">${['amount','count','rate','stock'].map(d=>`<option ${m.dimension===d?'selected':''}>${d}</option>`).join('')}</select></div></div>
 <div style="display:flex;gap:8px"><button class="btn" onclick="saveMetric()">保存（版本+1）</button><button class="btn ghost" onclick="closeModal()">取消</button></div>`)}
async function saveMetric(){try{await api('/v1/admin/metrics',{method:'POST',body:JSON.stringify({
 name:emn.value,display_name:emdn.value,formula:emf.value,aliases:ema.value,dimension:emd.value})});
 toast('已保存');closeModal();go('metrics')}catch(e){}}
/* 模型路由 */
RENDER.routing=async()=>{const rs=await api('/v1/admin/routes');
 page.innerHTML=`<div class="card"><div class="toolbar"><b style="font-size:13px">模型路由（任务→主模型→回退链）</b>
 <button class="btn sm" onclick="editRoute()">＋ 新建路由</button></div>
 <table><tr><th>task</th><th>主模型</th><th>回退链</th><th>重试</th><th>超时s</th><th>成本帽</th><th>状态</th><th></th></tr>
 ${rs.map(r=>`<tr><td class="mono">${esc(r.task)}</td><td>${esc(r.primary_model)}</td><td class="mono">${esc(r.fallback_models)}</td>
 <td>${r.max_attempts}</td><td>${r.timeout_s}</td><td>${r.cost_cap}</td><td>${tag(r.status,{active:'t-ok'})}</td>
 <td><button class="btn ghost sm" onclick='editRoute(${JSON.stringify(r).replace(/'/g,"&#39;")})'>编辑</button></td></tr>`).join('')}</table>
 <p class="hint" style="margin-top:10px">网关：LiteLLM（qwen2.5:14b 等）· 本地回退：Ollama（tinyllama/qwen3）· 集群内实测 10s 内出话</p></div>`};
function editRoute(r){r=r||{task:'',primary_model:'qwen2.5:14b',fallback_models:'qwen2.5-coder:7b',max_attempts:3,timeout_s:60,cost_cap:10,status:'active'};
 modal(`<h3>${r.task?'编辑':'新建'}路由</h3>
 <div class="row2"><div class="fld"><label>task</label><input id="ert" value="${esc(r.task)}" ${r.task?'disabled':''}></div>
 <div class="fld"><label>主模型</label><select id="erp">${['qwen2.5:14b','qwen2.5-coder:7b','qwen3:4b','tinyllama:latest'].map(m=>`<option ${r.primary_model===m?'selected':''}>${m}</option>`).join('')}</select></div></div>
 <div class="fld"><label>回退链（逗号分隔）</label><input id="erf" value="${esc(r.fallback_models)}"></div>
 <div class="row2"><div class="fld"><label>最大重试</label><input id="erm" type="number" value="${r.max_attempts}"></div>
 <div class="fld"><label>超时(秒)</label><input id="erto" type="number" value="${r.timeout_s}"></div></div>
 <div style="display:flex;gap:8px"><button class="btn" onclick="saveRoute()">保存</button><button class="btn ghost" onclick="closeModal()">取消</button></div>`)}
async function saveRoute(){try{await api('/v1/admin/routes',{method:'POST',body:JSON.stringify({
 task:ert.value,primary_model:erp.value,fallback_models:erf.value,max_attempts:+erm.value,timeout_s:+erto.value})});
 toast('已保存');closeModal();go('routing')}catch(e){}}
/* Capability 权限矩阵 */
RENDER.cap=async()=>{const c=await api('/v1/admin/capability');
 page.innerHTML=`<div class="grid" style="grid-template-columns:2fr 1fr">
 <div class="card"><b style="font-size:13px">工具 × 风险 × 角色可见性（来自内核 CapabilityRegistry）</b>
 <table style="margin-top:8px"><tr><th>工具</th><th>说明</th><th>风险</th><th>需审批</th><th>版本</th><th>可见角色</th></tr>
 ${c.tools.map(t=>`<tr><td class="mono">${esc(t.name)}</td><td>${esc(t.description)}</td>
 <td>${tag(t.risk_level,{readonly:'t-info',low:'t-info',medium:'t-warn',high:'t-err'})}</td>
 <td>${t.requires_approval?'✅':'—'}</td><td>${t.version}</td>
 <td class="mono">${t.visible_roles.join(',')}</td></tr>`).join('')}</table></div>
 <div><div class="card"><b style="font-size:13px">Skill</b><table style="margin-top:8px">
 ${c.skills.map(s=>`<tr><td class="mono">${esc(s.name)}</td><td>${esc(s.mission)}</td></tr>`).join('')}</table></div>
 <div class="card" style="margin-top:14px"><b style="font-size:13px">角色能力</b><table style="margin-top:8px">
 ${Object.entries(c.roles).map(([r,d])=>`<tr><td>${tag(r,{admin:'t-err',approver:'t-warn',analyst:'t-info',viewer:'t-mut'})}</td><td>${esc(d)}</td></tr>`).join('')}</table></div></div></div>`};
/* Memory 管理 */
RENDER.memory=async()=>{const ms=await api('/v1/admin/memory?limit=100');
 page.innerHTML=`<div class="card"><div class="toolbar"><b style="font-size:13px">长期记忆（写入策略/租户隔离/失效传播）</b>
 <div style="display:flex;gap:8px"><input id="mkey" placeholder="key（如 report_pref）" style="padding:6px 10px;border:1px solid #cbd5e1;border-radius:8px;width:150px">
 <input id="mval" placeholder="内容（如 用户偏好：周报柱状图）" style="padding:6px 10px;border:1px solid #cbd5e1;border-radius:8px;width:250px">
 <button class="btn sm" onclick="addMem()">写入</button></div></div>
 <table><tr><th>memory_id</th><th>key</th><th>内容</th><th>scope</th><th>版本</th><th>状态</th><th></th></tr>
 ${ms.map(m=>`<tr><td class="mono">${esc(m.memory_id.slice(0,12))}…</td><td class="mono">${esc(m.key)}</td><td>${esc(m.content.slice(0,30))}</td>
 <td>${esc(m.scope)}</td><td>v${m.version}</td><td>${m.active?tag('active','t-ok'):tag('deleted','t-mut')}</td>
 <td><button class="btn danger sm" onclick="delMem('${m.memory_id}')">删除(传播)</button></td></tr>`).join('')||'<tr><td colspan=7 class="empty">暂无记忆</td></tr>'}</table></div>`};
async function addMem(){if(!mkey.value||!mval.value)return toast('填 key 和内容',false);
 try{await api('/v1/admin/memory',{method:'POST',body:JSON.stringify({key:mkey.value,content:mval.value})});toast('已写入');go('memory')}catch(e){}}
async function delMem(id){try{await api(`/v1/admin/memory/${id}`,{method:'DELETE'});toast('已删除（软删+传播）');go('memory')}catch(e){}}
/* 发布与灰度 */
RENDER.release=async()=>{const s=await api('/v1/admin/release');
 page.innerHTML=`<div class="grid" style="grid-template-columns:1fr 2fr">
 <div class="card"><b style="font-size:13px">当前发布状态</b>
 <table style="margin-top:8px">
 <tr><th>版本</th><td class="mono">${esc(s.version)}</td></tr>
 <tr><th>灰度比例</th><td>${s.canary_pct}%</td></tr>
 <tr><th>Kill Switch</th><td>${s.kill_switch?tag('ON','t-err'):tag('OFF','t-ok')}</td></tr>
 <tr><th>回归门禁(code)</th><td>≥${s.regression_gate?.code ?? '—'}</td></tr></table>
 <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
 <button class="btn sm" onclick="setRelease({canary_pct:Math.min(100,(s.canary_pct||0)+25)})">灰度+25%</button>
 <button class="btn sm" onclick="setRelease({canary_pct:100})">全量</button>
 <button class="btn ghost sm" onclick="setRelease({canary_pct:0})">灰度归零</button>
 <button class="btn danger sm" onclick="toggleKill()">Kill Switch</button></div>
 <p class="hint" style="margin-top:10px">受控进化：候选评测 → 门禁 → 灰度 → 异常回滚（对应课程第九篇）</p></div>
 <div class="card"><b style="font-size:13px">发布历史</b>
 <table style="margin-top:8px"><tr><th>版本</th><th>状态</th></tr>
 ${(s.history||[]).slice().reverse().map(h=>`<tr><td class="mono">${esc(h.version)}</td><td>${tag(h.event,{released:'t-ok',rollback:'t-err',canary:'t-warn',gate_blocked:'t-warn'})}</td></tr>`).join('')||'<tr><td colspan=2 class="empty">暂无</td></tr>'}</table>
 <pre style="margin-top:12px">state = ${esc(JSON.stringify(s,null,2))}</pre></div></div>`};
let REL=null;
async function setRelease(patch){const s=await api('/v1/admin/release');REL={...s,...patch};
 try{const j=await api('/v1/admin/release',{method:'POST',body:JSON.stringify(REL)});toast('已更新 灰度='+j.canary_pct+'%');go('release')}catch(e){}}
async function toggleKill(){const s=await api('/v1/admin/release');
 try{const j=await api('/v1/admin/release',{method:'POST',body:JSON.stringify({...s,kill_switch:!s.kill_switch})});
 toast(j.kill_switch?'Kill Switch 已拉起（止血）':'Kill Switch 已解除');go('release')}catch(e){}}
/* API 测试 */
RENDER.api=async()=>{page.innerHTML=`<div class="card"><b style="font-size:13px">全接口回归（带当前 JWT）</b>
 <div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0">
 ${[['GET /healthz','/healthz','GET'],['GET /v1/admin/dashboard','/v1/admin/dashboard','GET'],
    ['GET /v1/admin/tenants','/v1/admin/tenants','GET'],['GET /v1/admin/metrics','/v1/admin/metrics','GET'],
    ['GET /v1/admin/routes','/v1/admin/routes','GET'],['GET /v1/admin/capability','/v1/admin/capability','GET'],
    ['GET /v1/admin/memory','/v1/admin/memory?limit=5','GET'],['GET /v1/admin/approvals','/v1/admin/approvals?status=pending','GET'],
    ['GET /v1/admin/tasks','/v1/admin/tasks?limit=5','GET'],['GET /v1/admin/release','/v1/admin/release','GET'],
    ['POST /v1/analysis 同步','/v1/analysis','POSTA'],['POST /v1/analysis 异步','/v1/analysis','POSTB'],
    ['GET /metrics','/metrics','GET']]
 .map((b,i)=>`<button class="btn ghost sm" onclick="runApi(${i})">${b[0]}</button>`).join('')}</div>
 <pre id="apiout">点击按钮执行…</pre></div>`};
const APIS=[['GET /healthz','/healthz','GET'],['GET /v1/admin/dashboard','/v1/admin/dashboard','GET'],
 ['GET /v1/admin/tenants','/v1/admin/tenants','GET'],['GET /v1/admin/metrics','/v1/admin/metrics','GET'],
 ['GET /v1/admin/routes','/v1/admin/routes','GET'],['GET /v1/admin/capability','/v1/admin/capability','GET'],
 ['GET /v1/admin/memory','/v1/admin/memory?limit=5','GET'],['GET /v1/admin/approvals','/v1/admin/approvals?status=pending','GET'],
 ['GET /v1/admin/tasks','/v1/admin/tasks?limit=5','GET'],['GET /v1/admin/release','/v1/admin/release','GET'],
 ['POST /v1/analysis 同步','/v1/analysis','POSTA'],['POST /v1/analysis 异步','/v1/analysis','POSTB'],
 ['GET /metrics','/metrics','GET']];
async function runApi(i){const [name,path,mode]=APIS[i];const t0=performance.now();
 try{let opt={headers:{'Authorization':'Bearer '+TOKEN}};
  if(mode==='POSTA')opt={...opt,method:'POST',headers:{...opt.headers,'Content-Type':'application/json'},body:JSON.stringify({query:'华东区 GMV 下滑诊断',tenant_id:'ten_a'})};
  if(mode==='POSTB')opt={...opt,method:'POST',headers:{...opt.headers,'Content-Type':'application/json'},body:JSON.stringify({query:'华东区 GMV 下滑诊断',tenant_id:'ten_a',async_:true})};
  const r=await fetch(API+path,opt);const j=await r.text();
  apiout.textContent=`${name} → HTTP ${r.status} (${(performance.now()-t0).toFixed(0)}ms)\n`+(r.status===200&&mode==='GET'&&name.includes('metrics ')&&path==='/metrics'?j.slice(0,300):(()=>{try{return JSON.stringify(JSON.parse(j),null,2).slice(0,1500)}catch(e){return j.slice(0,400)}})())}catch(e){apiout.textContent=name+' → '+e}}
/* 启动 */
if(TOKEN){try{const p=JSON.parse(atob(TOKEN.split('.')[1]));if(p.exp*1000>Date.now())enter();else logout()}catch(e){logout()}}
document.getElementById('lp').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()});
</script></body></html>"""
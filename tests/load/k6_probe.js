// k6 压测 v2 —— DataAgent API 真实部署（三阶段负载：smoke→load→spike）
// 用法（175 主机）: k6 run --summary-export=/tmp/k6-da.json tests/load/k6_probe.js
// 环境变量: BASE=http://10.167.2.175:30080
import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE || "http://10.167.2.175:30080";

export const options = {
  thresholds: {
    http_req_failed: ["rate<0.05"],
  },
  scenarios: {
    steady: {
      executor: "ramping-vus",
      startVUs: 5,
      stages: [
        { duration: "20s", target: 5 },
        { duration: "60s", target: 20 },
        { duration: "20s", target: 20 },
      ],
      exec: "steadyFlow",
    },
    spike: {
      executor: "ramping-vus",
      startVUs: 0,
      startTime: "1m45s",
      stages: [
        { duration: "15s", target: 40 },
        { duration: "20s", target: 40 },
        { duration: "15s", target: 0 },
      ],
      exec: "lightFlow",
    },
  },
};

function login() {
  const r = http.post(`${BASE}/login`,
    JSON.stringify({ username: "admin", password: "admin123" }),
    { headers: { "Content-Type": "application/json" }, name: "[public] /login" });
  check(r, { "login 201": (rr) => rr.status === 201 });
  return { Authorization: `Bearer ${r.json("token")}` };
}

export function steadyFlow() {
  const H = login();
  sleep(0.3);
  check(http.get(`${BASE}/healthz`, { name: "[public] /healthz" }),
    { "healthz 200": (r) => r.status === 200 });
  http.post(`${BASE}/v1/analysis`, JSON.stringify({
    query: "华东区 GMV 下滑诊断（k6 稳态）", tenant_id: "ten_a",
    user_id: "u1", async_: true,
  }), { headers: { ...H, "Content-Type": "application/json" }, name: "[biz] async enqueue" });
  http.get(`${BASE}/v1/admin/tasks`, { headers: H, name: "[admin] tasks" });
  sleep(0.5);
}

export function lightFlow() {
  const H = login();
  check(http.get(`${BASE}/readyz`, { name: "[public] /readyz" }),
    { "readyz 200": (r) => r.status === 200 });
  http.get(`${BASE}/v1/admin/dashboard`, { headers: H, name: "[admin] dashboard" });
  sleep(0.5);
}

export function setup() {
  const r = http.post(`${BASE}/login`,
    JSON.stringify({ username: "admin", password: "admin123" }),
    { headers: { "Content-Type": "application/json" } });
  check(r, { "setup login 201": (rr) => rr.status === 201 });
}

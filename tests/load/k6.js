import http from 'k6/http';
import { check, sleep } from 'k6';

// k6 压测脚本 —— DataAgent 已部署 K8S API (Litestar+Granian, NodePort:30080)
// 用法: k6 run tests/load/k6.js
export const options = {
    stages: [
        { duration: '20s', target: 200 },   // 爬坡到 200 VU
        { duration: '30s', target: 400 },   // 峰值 400 VU
        { duration: '15s', target: 0 },     // 下降
    ],
    thresholds: {
        http_req_failed: ['rate<0.01'],     // 失败率 <1%
        http_req_duration: ['p(95)<200'],   // P95<200ms
    },
};

const BASE = __ENV.BASE || 'http://10.167.2.176:30080';

export default function () {
    // 主打路径：异步入队(Pulsar) —— 百万并发友好（削峰）
    const data = {
        query: '华东区本月 GMV 下滑原因诊断',
        tenant_id: __VU % 3 === 0 ? 'ten_a' : 'ten_b',
        async_: true,
    };
    const res = http.post(`${BASE}/v1/analysis`, JSON.stringify(data), {
        headers: { 'Content-Type': 'application/json' },
    });
    check(res, { 'status is 2xx': (r) => r.status >= 200 && r.status < 300 });
    sleep(0.02);
}
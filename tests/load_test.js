import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 20 },  // Ramp-up to 20 users
    { duration: '1m', target: 20 },   // Stay at 20 users for 1 min
    { duration: '30s', target: 0 },   // Ramp-down to 0 users
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'], // 95% of requests must complete below 500ms
  },
};

export default function () {
  // Configured to ping the python backend running either locally or in Cloud Run
  const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

  let res = http.get(`${BASE_URL}/api/v1/health`);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'db is ok': (r) => r.json('db_status') === true,
  });

  sleep(1);
}

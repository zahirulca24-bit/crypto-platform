import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const read=p=>readFileSync(new URL(`../${p}`, import.meta.url),'utf8')
const ops=read('app/operations/page.tsx')
const api=read('lib/api.ts')
const settings=read('app/settings/page.tsx')
const confirm=read('components/confirm-action.tsx')

test('operations page is wired to real Phase 5 read APIs',()=>{
 for(const path of ['/v1/system/readiness','/v1/system/capabilities','/v1/portfolio/exposure','/v1/portfolio/capital-allocation','/v1/portfolio/risk-limits','/v1/safety/status','/v1/safety/circuit-breakers','/v1/reconciliation/status','/v1/operations/incidents','/v1/operations/alerts','/v1/security/exchange-credentials','/v1/security/audit-events']) assert.ok(ops.includes(path),path)
})
test('dangerous actions use confirmation and backend safety APIs',()=>{
 assert.ok(ops.includes('ConfirmAction')); assert.ok(ops.includes('/v1/safety/halt')); assert.ok(ops.includes('/v1/safety/resume')); assert.ok(confirm.includes('Confirm'))
})
test('live mode is visibly distinguished from demo',()=>{
 assert.ok(ops.includes('LIVE — REAL EXCHANGE EXECUTION')); assert.ok(ops.includes('text-red-300')); assert.ok(ops.includes('mode==="demo"'))
})
test('frontend exposes no exchange secret fields or private backend env vars',()=>{
 const all=[ops,settings,api].join('\n').toLowerCase()
 for(const forbidden of ['next_public_api_key','next_public_api_secret','next_public_database_url','next_public_redis_url','credential_encryption_key']) assert.equal(all.includes(forbidden),false,forbidden)
 assert.equal(ops.includes('api_secret'),false)
})
test('api base remains configurable and protected calls attach bearer session token',()=>{
 assert.ok(api.includes('NEXT_PUBLIC_API_BASE_URL')); assert.ok(api.includes('sessionStorage')); assert.ok(api.includes('Authorization: `Bearer ${token}`'))
})
test('production CORS assumptions are documented rather than hard-coded',()=>{
 assert.ok(settings.includes('CORS_ALLOW_ORIGINS')); assert.ok(settings.includes('exact deployed web origin'))
})

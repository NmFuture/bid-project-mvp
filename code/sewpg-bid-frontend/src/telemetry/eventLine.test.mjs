import test from 'node:test'
import assert from 'node:assert/strict'

import { splitEventsByLine, telemetryLineForRoute } from './eventLine.js'

test('telemetry line attribution follows the event route workspace', () => {
  assert.equal(telemetryLineForRoute('/workspace/business/projects/P-1'), 'business')
  assert.equal(telemetryLineForRoute('/workspace/tech/projects/P-1'), 'technical')
})

test('parse pages are attributed to their own line instead of defaulting to technical', () => {
  assert.equal(telemetryLineForRoute('/parse/business'), 'business')
  assert.equal(telemetryLineForRoute('/parse/business?projectId=P-1'), 'business')
  assert.equal(telemetryLineForRoute('/parse/technical'), 'technical')
})

test('routes outside any known workspace keep the historical technical default', () => {
  assert.equal(telemetryLineForRoute(''), 'technical')
  assert.equal(telemetryLineForRoute('/dashboard'), 'technical')
  assert.equal(telemetryLineForRoute('/workspace/unknown'), 'technical')
})

test('splitEventsByLine groups a mixed batch per line and strips the internal line field', () => {
  const groups = splitEventsByLine([
    { eventType: 'click', route: '/workspace/business', line: 'business', target: 'a' },
    { eventType: 'route', route: '/workspace/tech', line: 'technical', target: 'b' },
    { eventType: 'click', route: '/parse/business', line: 'business', target: 'c' },
  ])

  assert.deepEqual([...groups.keys()], ['business', 'technical'])
  assert.deepEqual(
    groups.get('business'),
    [
      { eventType: 'click', route: '/workspace/business', target: 'a' },
      { eventType: 'click', route: '/parse/business', target: 'c' },
    ],
  )
  assert.deepEqual(groups.get('technical'), [
    { eventType: 'route', route: '/workspace/tech', target: 'b' },
  ])
})

test('splitEventsByLine falls back to technical for events without a line tag', () => {
  const groups = splitEventsByLine([{ eventType: 'error', route: '/dashboard', target: 'x' }])
  assert.deepEqual([...groups.keys()], ['technical'])
  assert.equal(groups.get('technical').length, 1)
})

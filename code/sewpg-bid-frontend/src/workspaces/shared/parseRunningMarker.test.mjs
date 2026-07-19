import test from 'node:test'
import assert from 'node:assert/strict'

import {
  clearParseRunning,
  findRunningParseMarker,
  markParseRunning,
  readRunningParses,
} from './parseRunningMarker.js'

const createMemoryStorage = () => {
  const data = new Map()
  return {
    get length() {
      return data.size
    },
    key: (index) => Array.from(data.keys())[index] ?? null,
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => {
      data.set(String(key), String(value))
    },
    removeItem: (key) => {
      data.delete(key)
    },
    clear: () => data.clear(),
  }
}

const withMockStorage = (fn) => {
  const previousWindow = globalThis.window
  const storage = createMemoryStorage()
  globalThis.window = { localStorage: storage }
  try {
    return fn(storage)
  } finally {
    if (previousWindow === undefined) delete globalThis.window
    else globalThis.window = previousWindow
  }
}

test('marks and reads running parses from localStorage', () => {
  withMockStorage(() => {
    assert.equal(markParseRunning('PRJ-1', 'tech'), true)
    assert.equal(markParseRunning('PRJ-2', 'business'), true)

    const running = readRunningParses()
    assert.equal(running.length, 2)
    assert.deepEqual(
      running.map((item) => [item.projectId, item.bidType]),
      [['PRJ-1', 'tech'], ['PRJ-2', 'business']],
    )
    assert.ok(running.every((item) => Number.isFinite(item.startedAt) && item.startedAt > 0))
  })
})

test('clears a running parse marker by project and bid type', () => {
  withMockStorage(() => {
    markParseRunning('PRJ-1', 'tech')
    markParseRunning('PRJ-1', 'business')

    clearParseRunning('PRJ-1', 'tech')

    const running = readRunningParses()
    assert.equal(running.length, 1)
    assert.equal(running[0].bidType, 'business')
  })
})

test('drops expired markers and reports only fresh ones', () => {
  withMockStorage((storage) => {
    const now = Date.now()
    storage.setItem('bid:parse-running:tech:PRJ-OLD', JSON.stringify({
      projectId: 'PRJ-OLD',
      bidType: 'tech',
      startedAt: now - 7 * 60 * 60 * 1000,
    }))
    storage.setItem('bid:parse-running:business:PRJ-NEW', JSON.stringify({
      projectId: 'PRJ-NEW',
      bidType: 'business',
      startedAt: now - 1000,
    }))

    const running = readRunningParses(now)
    assert.equal(running.length, 1)
    assert.equal(running[0].projectId, 'PRJ-NEW')
    assert.equal(storage.getItem('bid:parse-running:tech:PRJ-OLD'), null)
  })
})

test('removes corrupted markers while reading', () => {
  withMockStorage((storage) => {
    storage.setItem('bid:parse-running:tech:PRJ-BAD', 'not-json')
    storage.setItem('bid:parse-running:business:PRJ-EMPTY', JSON.stringify({ bidType: 'business' }))
    storage.setItem('unrelated:key', '{}')

    assert.deepEqual(readRunningParses(), [])
    assert.equal(storage.getItem('bid:parse-running:tech:PRJ-BAD'), null)
    assert.equal(storage.getItem('bid:parse-running:business:PRJ-EMPTY'), null)
    assert.equal(storage.getItem('unrelated:key'), '{}')
  })
})

test('reads nothing when localStorage is unavailable', () => {
  assert.deepEqual(readRunningParses(), [])
  assert.equal(markParseRunning('PRJ-1', 'tech'), false)
})

test('finds the earliest running marker for a given bid type only', () => {
  withMockStorage(() => {
    markParseRunning('PRJ-B1', 'business')
    markParseRunning('PRJ-T1', 'tech')
    markParseRunning('PRJ-T2', 'tech')

    assert.equal(findRunningParseMarker('tech')?.projectId, 'PRJ-T1')
    assert.equal(findRunningParseMarker('business')?.projectId, 'PRJ-B1')
    assert.equal(findRunningParseMarker(''), null)
  })
})

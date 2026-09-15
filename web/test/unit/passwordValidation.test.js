import assert from 'node:assert/strict'
import test from 'node:test'

import { isPasswordLongEnough, MIN_PASSWORD_LENGTH } from '../../src/utils/passwordValidation.js'

test('password validation enforces the minimum length', () => {
  assert.equal(MIN_PASSWORD_LENGTH, 8)
  assert.equal(isPasswordLongEnough('1234567'), false)
  assert.equal(isPasswordLongEnough('12345678'), true)
})

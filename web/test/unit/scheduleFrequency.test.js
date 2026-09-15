import assert from 'node:assert/strict'

import {
  applyFrequencyChange,
  buildCronExpression,
  describeSchedule,
  parseCronExpression
} from '../../src/utils/scheduleFrequency.js'

assert.equal(buildCronExpression({ frequency: 'daily', time: '09:05' }), '5 9 * * *')
assert.equal(
  buildCronExpression({ frequency: 'weekly', time: '18:30', weekdays: [1, 5] }),
  '30 18 * * 1,5'
)
assert.equal(
  buildCronExpression({ frequency: 'yearly', time: '10:03', dayOfMonth: 5, month: 8 }),
  '3 10 5 8 *'
)
assert.deepEqual(parseCronExpression('0 9 * * 1-5'), {
  frequency: 'weekly',
  cronExpression: '0 9 * * 1-5',
  time: '09:00',
  weekdays: [1, 2, 3, 4, 5],
  dayOfMonth: 1,
  month: 1
})
assert.deepEqual(parseCronExpression('*/15 * * * *'), {
  frequency: 'custom',
  cronExpression: '*/15 * * * *',
  time: '09:00',
  weekdays: [1],
  dayOfMonth: 1,
  month: 1
})
assert.equal(
  buildCronExpression({ frequency: 'custom', cronExpression: '*/15 * * * *' }),
  '*/15 * * * *'
)
assert.equal(
  applyFrequencyChange(
    {
      frequency: 'weekly',
      cronExpression: '0 9 * * 1-5',
      time: '10:00',
      weekdays: [1, 2, 3, 4, 5]
    },
    'custom'
  ).cronExpression,
  '0 10 * * 1,2,3,4,5'
)
assert.equal(parseCronExpression('0 */2 * * *').frequency, 'custom')
assert.equal(parseCronExpression('0 9 * * 5-1').frequency, 'custom')
assert.equal(
  describeSchedule({ frequency: 'monthly', time: '10:03', dayOfMonth: 5 }),
  '每月 5 号 10:03'
)
assert.equal(
  describeSchedule({ frequency: 'weekly', time: '09:00', weekdays: [1, 2, 3, 4, 5] }),
  '工作日 09:00'
)

console.log('scheduleFrequency: all assertions passed')

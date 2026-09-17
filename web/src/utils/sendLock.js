export const SEND_LOCK_STORAGE_KEY = 'yuxi_send_lock'

const resolveStorage = (storage) =>
  storage || (typeof window !== 'undefined' ? window.localStorage : null)

export const readSendLockPreference = (storage) => {
  const targetStorage = resolveStorage(storage)
  if (!targetStorage) return false

  try {
    return targetStorage.getItem(SEND_LOCK_STORAGE_KEY) === 'locked'
  } catch {
    return false
  }
}

export const writeSendLockPreference = (locked, storage) => {
  const targetStorage = resolveStorage(storage)
  if (!targetStorage) return false

  try {
    targetStorage.setItem(SEND_LOCK_STORAGE_KEY, locked ? 'locked' : 'unlocked')
    return true
  } catch {
    return false
  }
}

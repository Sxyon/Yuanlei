export const isWorkspaceSymlinkConflict = (error) =>
  error?.response?.status === 409 &&
  error?.response?.data?.detail?.code === 'workspace_contains_symlinks'

export async function deleteWorkspaceEntries({
  entries,
  deletePath,
  confirmSafeCleanup,
  safeUnlinkSymlinks = false
}) {
  const deletedPaths = []
  for (let index = 0; index < entries.length; index += 1) {
    const entry = entries[index]
    try {
      await deletePath(entry.path, { safeUnlinkSymlinks })
      deletedPaths.push(entry.path)
    } catch (error) {
      if (safeUnlinkSymlinks || !isWorkspaceSymlinkConflict(error)) throw error

      const remainingEntries = entries.slice(index)
      if (!(await confirmSafeCleanup(remainingEntries))) {
        return { deletedPaths, cancelled: true }
      }
      const retried = await deleteWorkspaceEntries({
        entries: remainingEntries,
        deletePath,
        confirmSafeCleanup,
        safeUnlinkSymlinks: true
      })
      return {
        deletedPaths: [...deletedPaths, ...retried.deletedPaths],
        cancelled: retried.cancelled
      }
    }
  }
  return { deletedPaths, cancelled: false }
}

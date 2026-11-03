package io.github.nanomuse.guard

class SessionLocks(initial: Set<String>, private val save: (Set<String>) -> Unit, private val clock: () -> Long) {
    var ids = initial.toSet()
        private set
    private val leases = mutableMapOf<String, AccessLease>()
    @Synchronized fun isLocked(id: String, seconds: Int): Boolean = id in ids && leases[id]?.isUnlocked(seconds) != true
    @Synchronized fun protect(id: String, authenticated: Boolean) {
        if (authenticated) { leases.remove(id); ids = ids + id; save(ids) }
    }
    @Synchronized fun authenticate(id: String, success: Boolean) { leases.getOrPut(id) { AccessLease(clock) }.authenticate(success) }
    @Synchronized fun unprotect(id: String, authenticated: Boolean) { if (authenticated) deleted(id) }
    @Synchronized fun deleted(id: String) { leases.remove(id); ids = ids - id; save(ids) }
    @Synchronized fun leave(id: String, seconds: Int) { if (seconds == -1) leases.remove(id) }
}

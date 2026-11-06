package io.github.nanomuse.guard

import android.app.Activity
import org.junit.Assert.*
import org.junit.Test
import org.mockito.Mockito.mock

class AccessAuthenticationTest {
    @Test fun accessRefusesADeviceWithoutAScreenLock() {
        var accepted: Boolean? = null
        AccessAuthentication.confirm(mock(Activity::class.java), "Unlock") { accepted = it }
        assertEquals(false, accepted)
    }
    @Test fun optionalApprovalConfirmationRetainsItsExistingNoLockBehavior() {
        var accepted: Boolean? = null
        DeviceCredential.confirm(mock(Activity::class.java), "Approval", "Approval") { accepted = it }
        assertEquals(true, accepted)
    }
}

package io.github.nanomuse.cloud

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Text-message codes reach mainland-China numbers only: the screen says so before asking. */
class SignInIdentifierTest {

    @Test fun `what reads as a phone number`() {
        assertTrue(SignInIdentifier.looksLikePhone("13800000000"))
        assertTrue(SignInIdentifier.looksLikePhone("+86 138 0000 0000"))
        assertTrue(SignInIdentifier.looksLikePhone("+1 (415) 555-0100"))
        assertFalse(SignInIdentifier.looksLikePhone("someone@example.org"))
        assertFalse(SignInIdentifier.looksLikePhone("bob"))
        assertFalse(SignInIdentifier.looksLikePhone(""))
    }

    @Test fun `mainland numbers, with or without the country code`() {
        assertTrue(SignInIdentifier.isMainlandPhone("13800000000"))
        assertTrue(SignInIdentifier.isMainlandPhone("+8613800000000"))
        assertTrue(SignInIdentifier.isMainlandPhone("+86 138-0000-0000"))
        assertTrue(SignInIdentifier.isMainlandPhone("008613800000000"))
        assertTrue(SignInIdentifier.isMainlandPhone("8613800000000"))
        assertFalse(SignInIdentifier.isMainlandPhone("+14155550100"))
        assertFalse(SignInIdentifier.isMainlandPhone("+44 20 7946 0958"))
        assertFalse(SignInIdentifier.isMainlandPhone("+852 9123 4567"))
        assertFalse(SignInIdentifier.isMainlandPhone("+886 912 345 678"))
        assertFalse(SignInIdentifier.isMainlandPhone("23800000000")) // eleven digits, not a mobile prefix
        assertFalse(SignInIdentifier.isMainlandPhone("1380000000")) // ten digits
    }

    @Test fun `the warning shows for a number from elsewhere, not while typing, never for e-mail`() {
        assertTrue(SignInIdentifier.phoneOutsideMainland("+14155550100"))
        assertTrue(SignInIdentifier.phoneOutsideMainland("+852 9123 4567"))
        assertTrue(SignInIdentifier.phoneOutsideMainland("0044 20 7946 0958"))
        assertFalse(SignInIdentifier.phoneOutsideMainland("13800000000"))
        assertFalse(SignInIdentifier.phoneOutsideMainland("+86 138 0000 0000"))
        assertFalse(SignInIdentifier.phoneOutsideMainland("+1 415")) // still typing
        assertFalse(SignInIdentifier.phoneOutsideMainland("138"))
        assertFalse(SignInIdentifier.phoneOutsideMainland("someone@example.org"))
        assertFalse(SignInIdentifier.phoneOutsideMainland(""))
    }

    @Test fun `a mainland number on its way to eleven digits is not called abroad`() {
        // seven to ten digits that can still become 1xx xxxx xxxx: no sentence yet
        assertFalse(SignInIdentifier.phoneOutsideMainland("1380000"))
        assertFalse(SignInIdentifier.phoneOutsideMainland("138 0000 000"))
        assertFalse(SignInIdentifier.phoneOutsideMainland("+86 138 0000 000"))
        assertFalse(SignInIdentifier.phoneOutsideMainland("0086 138 0000 00"))
        assertFalse(SignInIdentifier.phoneOutsideMainland("86 138 0000 000"))
        // a verdict once it cannot be one any more
        assertTrue(SignInIdentifier.phoneOutsideMainland("23800000")) // a mainland mobile starts with 1
        assertTrue(SignInIdentifier.phoneOutsideMainland("138000000000")) // twelve digits
        assertTrue(SignInIdentifier.phoneOutsideMainland("+86 238 0000 000"))
        assertTrue(SignInIdentifier.phoneOutsideMainland("+1 415 555")) // another country code, seven digits
    }

    @Test fun `what could still become a mainland number`() {
        assertTrue(SignInIdentifier.couldBecomeMainland("1"))
        assertTrue(SignInIdentifier.couldBecomeMainland("1380000000"))
        assertTrue(SignInIdentifier.couldBecomeMainland("+861380000"))
        assertTrue(SignInIdentifier.couldBecomeMainland("861380000"))
        assertFalse(SignInIdentifier.couldBecomeMainland("13800000000")) // complete: a verdict of its own
        assertFalse(SignInIdentifier.couldBecomeMainland("+1415"))
        assertFalse(SignInIdentifier.couldBecomeMainland("2380"))
        assertFalse(SignInIdentifier.couldBecomeMainland(""))
    }
}

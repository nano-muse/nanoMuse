// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse background screen wireless setup.
package io.github.nanomuse.hands.pairing

import android.content.ActivityNotFoundException
import android.content.ContentResolver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings

/**
 * Reads Android developer/debugging toggles and builds intents that jump directly to the
 * relevant system settings screen, highlighting the target row when supported by AOSP Settings.
 */
internal object DeveloperSettings {
    const val ADB_WIFI_ENABLED = "adb_wifi_enabled"
    private const val WIRELESS_DEBUGGING_KEY = "toggle_adb_wireless"
    private const val USB_DEBUGGING_KEY = "enable_adb"
    private const val EXTRA_FRAGMENT_ARG_KEY = ":settings:fragment_args_key"
    private const val EXTRA_SHOW_FRAGMENT_ARGS = ":settings:show_fragment_args"

    val developerOptionsUri: Uri = Settings.Global.getUriFor(Settings.Global.DEVELOPMENT_SETTINGS_ENABLED)
    val usbDebuggingUri: Uri = Settings.Global.getUriFor(Settings.Global.ADB_ENABLED)
    val wirelessDebuggingUri: Uri = Settings.Global.getUriFor(ADB_WIFI_ENABLED)

    fun developerOptions(cr: ContentResolver): Boolean =
        runCatching { Settings.Global.getInt(cr, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) == 1 }
            .getOrDefault(false)

    fun usbDebugging(cr: ContentResolver): Boolean =
        runCatching { Settings.Global.getInt(cr, Settings.Global.ADB_ENABLED, 0) == 1 }
            .getOrDefault(false)

    /**
     * Reads wireless debugging state. Returns null when the ROM does not expose the setting or
     * blocks reads, so the setup state machine never gets stuck on vendor quirks.
     */
    fun wirelessDebugging(cr: ContentResolver): Boolean? = runCatching {
        when (Settings.Global.getString(cr, ADB_WIFI_ENABLED)?.trim()) {
            "1" -> true
            "0" -> false
            null -> false
            else -> null
        }
    }.getOrNull()

    fun wirelessDebuggingMissing(cr: ContentResolver): Boolean =
        runCatching { Settings.Global.getString(cr, ADB_WIFI_ENABLED) == null }.getOrDefault(false)

    fun developerOptionsPageMissing(pm: PackageManager): Boolean =
        runCatching { pm.resolveActivity(Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS), 0) == null }
            .getOrDefault(false)

    fun settingsPackage(pm: PackageManager): String? =
        runCatching { pm.resolveActivity(Intent(Settings.ACTION_SETTINGS), 0)?.activityInfo?.packageName }.getOrNull()

    fun wifiConnected(context: Context): Boolean = runCatching {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val active = cm.activeNetwork ?: return false
        cm.getNetworkCapabilities(active)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
    }.getOrDefault(true)

    fun restrictedSettingsLikely(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return false
        return runCatching {
            val installer = context.packageManager.getInstallSourceInfo(context.packageName).installingPackageName
            installer == null
        }.getOrDefault(true)
    }

    fun aboutPhone(): List<Intent> = listOf(
        Intent(Settings.ACTION_DEVICE_INFO_SETTINGS),
        Intent(Settings.ACTION_SETTINGS),
    )

    fun developerOptionsPage(): List<Intent> = listOf(
        Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS),
        Intent(Settings.ACTION_SETTINGS),
    )

    fun usbDebuggingPage(): List<Intent> = highlighted(USB_DEBUGGING_KEY)

    fun wirelessDebuggingPage(): List<Intent> = highlighted(WIRELESS_DEBUGGING_KEY)

    fun accessibilityPage(): List<Intent> = listOf(
        Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS),
        Intent(Settings.ACTION_SETTINGS),
    )

    fun wifiPage(): List<Intent> = listOf(
        Intent(Settings.ACTION_WIFI_SETTINGS),
        Intent(Settings.ACTION_SETTINGS),
    )

    fun appInfoPage(packageName: String): List<Intent> = listOf(
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)),
        Intent(Settings.ACTION_SETTINGS),
    )

    fun appNotificationsPage(packageName: String): List<Intent> = listOf(
        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName),
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)),
    )

    fun channelNotificationsPage(packageName: String, channelId: String): List<Intent> = listOf(
        Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
            .putExtra(Settings.EXTRA_CHANNEL_ID, channelId),
        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName),
    )

    fun launchFirst(context: Context, intents: List<Intent>): Boolean = intents.any { intent ->
        try {
            context.startActivity(Intent(intent).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (_: ActivityNotFoundException) {
            false
        } catch (_: SecurityException) {
            false
        }
    }

    private fun highlighted(key: String): List<Intent> {
        val highlight = Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS)
            .putExtra(EXTRA_FRAGMENT_ARG_KEY, key)
            .putExtra(EXTRA_SHOW_FRAGMENT_ARGS, Bundle().apply { putString(EXTRA_FRAGMENT_ARG_KEY, key) })
        return listOf(highlight) + developerOptionsPage()
    }
}

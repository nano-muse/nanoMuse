# Tink references errorprone annotations that aren't shipped at runtime
-dontwarn com.google.errorprone.annotations.**

# [T-android-vad-jni-keep / GH#250] RealTimeCutVAD's C++ layer calls back into
# VADWrapper BY NAME through JNI (GetMethodID "onVoiceStart" / "onVoiceEnd" /
# "onVoiceDidContinue"). Those three are PRIVATE Java methods with no Java-side
# caller, so R8 sees them as dead and renames them — verified in the shipped
# 1.12 release dex, where they had become b()V / c()V / d()V and the `callback`
# field was removed outright. The native lookup then fails with
#
#   java.lang.NoSuchMethodError: no non-static method
#   "Lio/codeconcept/realtimecutvadlibrary/VADWrapper;.onVoiceStart()V"
#
# thrown from processAudio (a native method), which is exactly the reported
# crash: every release user who tapped the mic got "Voice detection failed"
# before any STT provider was even contacted.
#
# proguard-android-optimize.txt keeps `native` method DECLARATIONS and @Keep,
# but nothing protects an ordinary Java method that only native code invokes.
#
# Kept whole rather than member-scoped: the library is five classes, so the
# size cost is negligible, whereas a narrow rule that missed a member the
# native side also touches (the `vadInstance` handle, for one) would degrade
# into a subtler runtime failure.
#
# NOTE FOR VERIFICATION: debug builds don't minify, so this bug is invisible
# there. Any change here must be checked against an assembleRelease APK.
-keep class io.codeconcept.realtimecutvadlibrary.** { *; }

# nanoMuse: SnakeYAML uses field access on Android. Its optional desktop
# JavaBeans introspection path references these classes from java.desktop.
-dontwarn java.beans.BeanInfo
-dontwarn java.beans.FeatureDescriptor
-dontwarn java.beans.IntrospectionException
-dontwarn java.beans.Introspector
-dontwarn java.beans.PropertyDescriptor

# nanoMuse: Rhino resolves its interpreter, VM bridge, RegExp and built-in JS
# constructors by name. The phone uses its interpreter with safe standard objects.
-keep class org.mozilla.javascript.Interpreter { *; }
-keep class org.mozilla.javascript.jdk18.VMBridge_jdk18 { *; }
-keep class org.mozilla.javascript.regexp.** { *; }
-keep class org.mozilla.javascript.NativeContinuation { *; }
-keep class org.mozilla.javascript.typedarrays.** { *; }
-keepnames class org.mozilla.javascript.Context
-keepnames class org.mozilla.javascript.ContextFactory
-keepnames interface org.mozilla.javascript.Function
-keepnames class org.mozilla.javascript.ScriptableObject
# Optional Java bean conversion is unreachable: no Java objects enter the JS scope.
-dontwarn java.beans.BeanDescriptor

# nanoMuse: the authenticated wireless-debugging transport invokes this fixed entry point by name.
-keep class io.github.nanomuse.hands.HandsDisplayBridgeMain { public static void main(java.lang.String[]); }

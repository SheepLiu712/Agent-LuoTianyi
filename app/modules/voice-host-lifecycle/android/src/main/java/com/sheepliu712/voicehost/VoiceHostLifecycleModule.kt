package com.sheepliu712.voicehost

import android.app.Activity
import android.app.Application
import android.os.Bundle
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class VoiceHostLifecycleModule : Module(), Application.ActivityLifecycleCallbacks {
  private var application: Application? = null

  override fun definition() = ModuleDefinition {
    Name("VoiceHostLifecycle")
    Events("onHostStopped")

    OnCreate {
      val context = requireNotNull(appContext.reactContext)
      application = context.applicationContext as Application
      application?.registerActivityLifecycleCallbacks(this@VoiceHostLifecycleModule)
    }
    OnDestroy {
      application?.unregisterActivityLifecycleCallbacks(this@VoiceHostLifecycleModule)
      application = null
    }
  }

  override fun onActivityStopped(activity: Activity) {
    // Android pauses the host behind a permission dialog; STOP means it is no longer visible.
    if (activity === appContext.currentActivity) sendEvent("onHostStopped")
  }

  override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) = Unit
  override fun onActivityStarted(activity: Activity) = Unit
  override fun onActivityResumed(activity: Activity) = Unit
  override fun onActivityPaused(activity: Activity) = Unit
  override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
  override fun onActivityDestroyed(activity: Activity) = Unit
}

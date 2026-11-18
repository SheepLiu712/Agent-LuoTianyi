package com.sheepliu712.callaudio

import org.junit.Assert.*
import org.junit.Test

class HeadsetRouteSelectionTest {
  @Test fun `selects the media headset among multiple bluetooth devices`() {
    assertEquals(8, HeadsetRouteSelection.select(RouteDevice(1, "AA", true), listOf(
      RouteDevice(7, "BB", true), RouteDevice(8, "aa", true),
    )))
  }

  @Test fun `supports vendor SCO placeholder address when endpoint is unique`() {
    assertEquals(8, HeadsetRouteSelection.select(RouteDevice(1, "AA", true), listOf(
      RouteDevice(8, "00:00:00:00:00:00", true),
    )))
  }

  @Test(expected = IllegalStateException::class)
  fun `does not guess between multiple unmatched headsets`() {
    HeadsetRouteSelection.select(RouteDevice(1, "AA", true), listOf(
      RouteDevice(7, "", true), RouteDevice(8, "", true),
    ))
  }

  @Test fun `blocks unknown and speaker routes including mixed output`() {
    assertFalse(HeadsetRouteSelection.ready(8, emptyList()))
    assertFalse(HeadsetRouteSelection.ready(8, listOf(2)))
    assertFalse(HeadsetRouteSelection.ready(8, listOf(8, 2)))
    assertTrue(HeadsetRouteSelection.ready(8, listOf(8)))
  }

  @Test(expected = IllegalStateException::class)
  fun `rejects a different connected headset with a known address`() {
    HeadsetRouteSelection.select(RouteDevice(1, "AA", true), listOf(RouteDevice(8, "BB", true)))
  }

  @Test fun `keeps a directly addressable wired headset`() {
    assertEquals(4, HeadsetRouteSelection.select(RouteDevice(4, "", false), listOf(RouteDevice(4, "", false))))
  }
}

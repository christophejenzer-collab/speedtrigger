"""Auslösen der Canon EOS über das EDSDK (USB), direkt per ctypes – kein Kompilieren nötig.

Alle EDSDK-Aufrufe laufen in EINEM eigenen Thread (Canon-Vorgabe unter Windows),
die Hauptschleife stellt nur Aufträge in eine Queue und wird nie blockiert.
"""
import os
import queue
import sys
import threading
import time
import ctypes as C

# Konstanten aus EDSDKTypes.h
EDS_ERR_OK = 0x00000000
EDS_ERR_DEVICE_BUSY = 0x00000081
CMD_PRESS_SHUTTER = 0x00000004
SHUTTER_OFF = 0x00000000
SHUTTER_COMPLETELY = 0x00000003
SHUTTER_COMPLETELY_NON_AF = 0x00010003
PROP_SAVE_TO = 0x0000000B
SAVE_TO_CAMERA = 1


class DummyKamera:
    """Ohne Kamera testen: protokolliert nur."""

    def __init__(self, cfg):
        self.cfg = cfg
        print("[Kamera] Dummy-Modus – es wird nicht wirklich ausgelöst")

    def ausloesen(self):
        print(f"[Kamera] *** KLICK *** ({time.strftime('%H:%M:%S')})")

    def schliessen(self):
        pass


class EdsdkKamera:
    def __init__(self, cfg):
        if sys.platform != "win32":
            raise SystemExit("Dieser EDSDK-Wrapper ist für Windows gebaut (EDSDK.dll).")
        self.cfg = cfg
        self.q = queue.Queue()
        self.bereit = threading.Event()
        self.fehler = None
        threading.Thread(target=self._lauf, daemon=True).start()
        self.bereit.wait(15)
        if self.fehler:
            raise SystemExit(f"[Kamera] {self.fehler}")
        if not self.bereit.is_set():
            raise SystemExit("[Kamera] Zeitüberschreitung beim Verbinden")

    # --- Thread mit allen SDK-Aufrufen -------------------------------------------------
    def _lauf(self):
        try:
            self._verbinden()
        except Exception as e:  # noqa: BLE001
            self.fehler = str(e)
            self.bereit.set()
            return
        self.bereit.set()
        while True:
            try:
                auftrag = self.q.get(timeout=0.2)
            except queue.Empty:
                self.sdk.EdsGetEvent()  # Ereignisse abholen, hält die Verbindung wach
                continue
            if auftrag is None:
                break
            try:
                self._klick()
            except Exception as e:  # noqa: BLE001
                print(f"[Kamera] Auslösen fehlgeschlagen: {e}")
        self.sdk.EdsCloseSession(self.cam)
        self.sdk.EdsRelease(self.cam)
        self.sdk.EdsTerminateSDK()
        print("[Kamera] Sitzung geschlossen")

    def _pruefen(self, err, was):
        if err != EDS_ERR_OK:
            raise RuntimeError(f"{was} -> EDSDK-Fehler 0x{err:08X}")

    def _verbinden(self):
        dll = self.cfg["edsdk_dll"]
        if not os.path.isfile(dll):
            raise RuntimeError(f"EDSDK.dll nicht gefunden: {dll}")
        os.add_dll_directory(os.path.dirname(os.path.abspath(dll)))  # EdsImage.dll liegt daneben
        self.sdk = sdk = C.WinDLL(dll)  # EDSAPI = __stdcall
        for name in ("EdsInitializeSDK", "EdsTerminateSDK", "EdsGetCameraList", "EdsGetChildCount",
                     "EdsGetChildAtIndex", "EdsOpenSession", "EdsCloseSession", "EdsRelease",
                     "EdsSendCommand", "EdsSetPropertyData", "EdsGetEvent"):
            getattr(sdk, name).restype = C.c_uint32
        sdk.EdsSendCommand.argtypes = [C.c_void_p, C.c_uint32, C.c_int32]
        sdk.EdsSetPropertyData.argtypes = [C.c_void_p, C.c_uint32, C.c_int32, C.c_uint32, C.c_void_p]

        self._pruefen(sdk.EdsInitializeSDK(), "EdsInitializeSDK")
        liste = C.c_void_p()
        self._pruefen(sdk.EdsGetCameraList(C.byref(liste)), "EdsGetCameraList")
        anzahl = C.c_uint32()
        self._pruefen(sdk.EdsGetChildCount(liste, C.byref(anzahl)), "EdsGetChildCount")
        if anzahl.value == 0:
            sdk.EdsRelease(liste)
            raise RuntimeError("Keine Canon-Kamera gefunden (USB, Kamera EIN, EOS Utility geschlossen?)")
        self.cam = C.c_void_p()
        self._pruefen(sdk.EdsGetChildAtIndex(liste, 0, C.byref(self.cam)), "EdsGetChildAtIndex")
        sdk.EdsRelease(liste)
        self._pruefen(sdk.EdsOpenSession(self.cam), "EdsOpenSession")
        ziel = C.c_uint32(SAVE_TO_CAMERA)  # Bilder auf die SD-Karte der Kamera
        self._pruefen(sdk.EdsSetPropertyData(self.cam, PROP_SAVE_TO, 0, 4, C.byref(ziel)), "SaveTo")
        print("[Kamera] EOS verbunden, Bilder werden auf der Speicherkarte gespeichert")

    def _klick(self):
        modus = SHUTTER_COMPLETELY if self.cfg["autofokus"] else SHUTTER_COMPLETELY_NON_AF
        for _ in range(20):  # Kamera kurz beschäftigt (z. B. schreibt noch) -> wiederholen
            err = self.sdk.EdsSendCommand(self.cam, CMD_PRESS_SHUTTER, modus)
            if err != EDS_ERR_DEVICE_BUSY:
                break
            time.sleep(0.05)
        self._pruefen(err, "Auslöser drücken")
        if self.cfg["serie_ms"] > 0:
            time.sleep(self.cfg["serie_ms"] / 1000)  # Auslöser gedrückt halten = Serie
        self._pruefen(self.sdk.EdsSendCommand(self.cam, CMD_PRESS_SHUTTER, SHUTTER_OFF), "Auslöser loslassen")
        print(f"[Kamera] *** KLICK *** ({time.strftime('%H:%M:%S')})")

    # --- öffentliche API --------------------------------------------------------------
    def ausloesen(self):
        self.q.put("klick")

    def schliessen(self):
        self.q.put(None)
        time.sleep(0.5)


class KeineKamera:
    """Zählmodus: keine Kamera, keine Bilder."""

    def __init__(self, cfg):
        pass

    def ausloesen(self):
        pass

    def schliessen(self):
        pass


def kamera_erstellen(cfg):
    return {"edsdk": EdsdkKamera, "dummy": DummyKamera, "aus": KeineKamera}[cfg["typ"]](cfg)

Rise and Fall Remaster 1.0 - Installer
by Alexander West - thewest.cc/raf

Was es macht
- Sucht dein installiertes "Rise and Fall: Civilization at War" (russische Version 1.15).
- Kopiert es in einen neuen Ordner (Standard: "Rise and Fall Remaster" neben dem Original).
  Das Originalspiel wird nur gelesen und nie verändert.
- Baut das Remaster in der Kopie aus deinen eigenen Spieldateien: randloses Vollbild,
  flüssiges Scrollen, weiterer Zoom (Regler unter Optionen > Interface), Ultra-Grafik,
  Mipmaps, neue Shader, optional HD-Texturen (auf deiner Grafikkarte hochskaliert),
  härtere KI mit Persönlichkeiten, bessere Einheiten-KI, Einheitenlimit 10000 und der
  Koop-Modus "Survival".
- Legt Verknüpfungen an (Spielen, Netzwerkspiel hosten/beitreten, Deinstallieren).

Der Installer enthält keine Spieldateien. Du brauchst eine eigene Kopie des Spiels.

Netzwerkspiel
- Am Ende zeigt der Installer einen Gameplay-Fingerabdruck (auch in REMASTER.txt im
  Spielordner). Alle Spieler brauchen denselben Fingerabdruck, sonst bricht das Spiel ab.
- "Netzwerkspiel hosten" öffnet direkt eine LAN-Lobby, "Netzwerkspiel beitreten" fragt
  nach der IP des Hosts.

Deinstallieren
- Startmenü "Rise and Fall Remaster deinstallieren", Windows-Einstellungen > Apps, oder
  Deinstallieren.bat im Remaster-Ordner. Das löscht den Remaster-Ordner, die Verknüpfungen
  und setzt die Registry-Werte zurück, die der Installer geändert hat.
- Hinweis: Original und Remaster teilen sich die Spieleinstellungen in der Registry
  (Auflösung, Grafik). Das Original übernimmt sie daher, solange das Remaster installiert ist.

Fehler
- Das Protokoll steht in %TEMP%\RaF-Remaster-Setup.log.

Lizenzen
- Remaster-Code: MIT (LICENSE.txt). Mitgelieferte Programme und ihre Lizenzen:
  Ordner "licenses" bzw. "Remaster-Lizenzen" im Spielordner (DXVK, texconv/DirectXTex,
  Real-ESRGAN ncnn Vulkan + Modell, ncnn, Python, NumPy, Pillow, pefile, Tcl/Tk,
  PyInstaller).

English: copies your own Rise and Fall (Russian v1.15) to a new folder and builds the
remaster there from your own game files. Contains no game files.
